"""Link stage (#3 Context Linking): sender → person, message → case, rolling case summary.

Order: same thread → the person's only open case → `link_check` agent among several open cases → new case.
The model only ever chooses among listed candidates (`accept_link`). A per-person advisory lock serialises the
"new case" decision, so two messages from one sender arriving together never open two cases. Replays return the
existing link unchanged.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.context.person_profile import mark_stale, person_profile_line
from app.contracts import CaseState, Category, Channel, Direction, Urgency, WaitingSide
from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import LinkMethod, PersonKind
from app.db.models import (
    AttachmentRow,
    Case,
    CaseLink,
    Company,
    LeaseParty,
    MessageRow,
    Person,
    PersonProfile,
    UnderstandingRow,
)
from app.llm.agents.case_summary import CASE_SUMMARY, case_summary_prompt
from app.llm.agents.link_check import LINK_CHECK, CandidateCase, accept_link, link_check_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import case_repo, chasing, work_repo

log = get_logger(__name__)
_URGENCY_RANK = {Urgency.low: 0, Urgency.normal: 1, Urgency.high: 2, Urgency.emergency: 3}


@dataclass(frozen=True)
class LinkResult:
    case_id: UUID
    method: LinkMethod
    person_id: UUID


@dataclass(frozen=True)
class _Facts:
    message_id: UUID
    company_id: UUID
    person_id: UUID | None
    sender: str
    text: str
    sent_at: datetime
    category: Category
    urgency: Urgency
    requires_reply: bool = True
    suspicious: bool = False
    unreadable_stranger: bool = False
    direction: Direction = Direction.inbound
    waiting_side: WaitingSide = WaitingSide.owner
    open_obligation: str | None = None
    expected_days: int | None = None
    expected_date: date | None = None


def _has_attachments(session: Session, msg: MessageRow) -> bool:
    found = session.scalar(
        select(AttachmentRow.id).where(AttachmentRow.company_id == msg.company_id, AttachmentRow.message_id == msg.id)
    )
    return found is not None


def _load(session: Session, message_id: UUID) -> _Facts | LinkResult | None:
    msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))
    if msg is None:
        return None
    link = session.scalar(select(CaseLink).where(CaseLink.company_id == msg.company_id, CaseLink.message_id == msg.id))
    if link is not None and msg.person_id is not None:
        return LinkResult(link.case_id, link.method, msg.person_id)
    und = session.scalar(
        select(UnderstandingRow).where(
            UnderstandingRow.company_id == msg.company_id, UnderstandingRow.message_id == msg.id
        )
    )
    category, urgency = (und.category, und.urgency) if und else (Category.administration, Urgency.normal)
    if category is Category.spam and (not msg.text.strip() or _has_attachments(session, msg)):
        category = Category.administration  # a photo or file with no words is never dropped as spam: Harjot sees it
    body = und.body if und else {}

    # Non-Actionable Fallback on Crash:
    # When understanding failed (und is None) or is unreadable, check if sender is an established property contact
    is_known_contact = False
    if msg.person_id:
        person = session.get(Person, msg.person_id)
        if (person and getattr(person, "kind", None) in (PersonKind.tenant, PersonKind.contractor)) or session.scalar(
            select(LeaseParty.id).where(LeaseParty.company_id == msg.company_id, LeaseParty.person_id == msg.person_id)
        ) is not None:
            is_known_contact = True

    if und is None and not is_known_contact:
        # Unlinked stranger or marketing sender with failed understanding:
        # do not require a reply or open a primary triage case
        requires_reply = False
        unreadable_stranger = True
    else:
        requires_reply = bool(body.get("requires_reply", category is not Category.spam))
        unreadable_stranger = False

    suspicious = bool((body.get("suspicious") or {}).get("flag", False))
    raw_ws = body.get("waiting_side")
    try:
        waiting_side = WaitingSide(raw_ws) if raw_ws else (WaitingSide.owner if requires_reply else WaitingSide.none)
    except ValueError:
        waiting_side = WaitingSide.owner if requires_reply else WaitingSide.none
    raw_ob = body.get("open_obligation")
    open_obligation = str(raw_ob).strip()[:200] if isinstance(raw_ob, str) and raw_ob.strip() else None
    raw_days = body.get("expected_days")
    expected_days = raw_days if isinstance(raw_days, int) and 1 <= raw_days <= 60 else None
    raw_date = body.get("expected_date")
    expected_date: date | None = None
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            expected_date = date.fromisoformat(raw_date.strip()[:10])
        except ValueError:
            expected_date = None
    return _Facts(
        msg.id,
        msg.company_id,
        msg.person_id,
        msg.sender_identity,
        msg.text,
        msg.sent_at,
        category,
        urgency,
        requires_reply,
        suspicious,
        unreadable_stranger,
        msg.direction,
        waiting_side,
        open_obligation,
        expected_days,
        expected_date,
    )


def _ask_model(
    engine: Engine,
    settings: Settings,
    f: _Facts,
    cands: list[CandidateCase],
    profile_line: str | None = None,
) -> UUID | None:
    prompt = link_check_prompt(f.text, f.category, cands, profile_line)
    try:
        result = run_agent(
            engine, settings, LINK_CHECK, prompt, CallContext(f.company_id, "link_check", message_ids=(f.message_id,))
        )
    except AgentFailedError:
        log.warning("pipeline.link_check_failed", message_id=str(f.message_id))
        return None
    return accept_link(result.output, cands)


def _choose(engine: Engine, settings: Settings, f: _Facts, person_id: UUID) -> tuple[UUID | None, LinkMethod]:
    with Session(engine) as session:
        msg = session.get(MessageRow, f.message_id)
        thread = case_repo.thread_case(session, f.company_id, msg) if msg else None
        if thread is not None:
            return thread, LinkMethod.thread
        # Email threads follow Gmail thread / RFC reply headers only: two separate emails from the same
        # address must never be merged into one thread.
        if msg is not None and msg.channel is Channel.gmail:
            return None, LinkMethod.new_case
        open_cases = case_repo.open_candidates(session, f.company_id, person_id, channel=msg.channel if msg else None)
        profile = session.scalar(
            select(PersonProfile).where(PersonProfile.company_id == f.company_id, PersonProfile.person_id == person_id)
        )
        profile_line = person_profile_line(profile)
    if len(open_cases) == 1:
        return open_cases[0].case_id, LinkMethod.open_case
    if not open_cases:
        # Check if the person is linked to a unit with an existing Case for an open BRIXX ticket
        if f.category == Category.maintenance:
            with Session(engine) as session:
                brixx_filters = [
                    Case.company_id == f.company_id,
                    Case.primary_person_id == person_id,
                    Case.category == Category.maintenance,
                    Case.state.in_(case_repo.OPEN_STATES),
                    Case.brixx_ref.is_not(None),
                ]
                if msg is not None:
                    brixx_filters.append(case_repo.no_other_channel_messages(f.company_id, msg.channel))
                matching_brixx_case = session.scalar(
                    select(Case.id).where(*brixx_filters).order_by(Case.opened_at.desc()).limit(1)
                )
                if matching_brixx_case:
                    return matching_brixx_case, LinkMethod.open_case
        return None, LinkMethod.new_case
    cands = [CandidateCase(c.case_id, c.category, c.summary, c.last_message_at) for c in open_cases]
    chosen = _ask_model(engine, settings, f, cands, profile_line)
    return (chosen, LinkMethod.model) if chosen else (None, LinkMethod.new_case)


def _record(engine: Engine, f: _Facts, person_id: UUID, case_id: UUID | None, method: LinkMethod) -> LinkResult:
    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"person:{person_id}"})
        if case_id is None:  # re-check under the lock: a sibling message may have opened the case meanwhile
            msg = session.get(MessageRow, f.message_id)
            case_id = case_repo.thread_case(session, f.company_id, msg) if msg else None
            method = LinkMethod.thread if case_id else LinkMethod.new_case
        if case_id is None:
            case_id = case_repo.create_case(session, f.company_id, person_id, f.category, f.urgency)
        case_repo.link_message(session, f.company_id, case_id, f.message_id, method, None)
        _after_link(session, f, person_id, case_id)
        return LinkResult(case_id, method, person_id)


def _transition_via_open(session: Session, company_id: UUID, case: Case, target: CaseState) -> None:
    if case.state is target or case.state in (CaseState.resolved, CaseState.closed):
        return
    if case.state is not CaseState.open:
        case_repo.transition(session, company_id, case.id, CaseState.open, actor="system")
    if target is not CaseState.open:
        case_repo.transition(session, company_id, case.id, target, actor="system")


def _company_tz(session: Session, company_id: UUID) -> str:
    company = session.get(Company, company_id)
    return company.timezone if company is not None else chasing.DEFAULT_TZ


def _latest_inbound_deadline(session: Session, company_id: UUID, case_id: UUID) -> tuple[date | None, int | None]:
    row = session.execute(
        select(UnderstandingRow.body)
        .join(MessageRow, MessageRow.id == UnderstandingRow.message_id)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id == case_id,
            UnderstandingRow.company_id == company_id,
            MessageRow.company_id == company_id,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not isinstance(row, dict):
        return None, None
    exp_date: date | None = None
    raw_date = row.get("expected_date")
    if isinstance(raw_date, str) and raw_date.strip():
        try:
            exp_date = date.fromisoformat(raw_date.strip()[:10])
        except ValueError:
            exp_date = None
    raw_days = row.get("expected_days")
    exp_days = raw_days if isinstance(raw_days, int) and 1 <= raw_days <= 60 else None
    return exp_date, exp_days


def _resolve_deadline(
    session: Session,
    f: _Facts,
    *,
    case_id: UUID,
    tz: str,
    inherit_inbound: bool = False,
) -> tuple[datetime, bool]:
    """Return `(due_at_utc, is_explicit)` using promised calendar date (next morning 09:00 local) when present."""
    local_day = f.sent_at.astimezone(ZoneInfo(tz)).date()
    exp_date, exp_days = f.expected_date, f.expected_days
    if exp_date is None and exp_days is None and inherit_inbound:
        inb_date, inb_days = _latest_inbound_deadline(session, f.company_id, case_id)
        if inb_date is not None and inb_date >= local_day:
            exp_date = inb_date
        elif inb_days is not None:
            exp_days = inb_days
    if exp_date is not None:
        return chasing.next_morning_after(max(exp_date, local_day), tz), True
    if exp_days is not None:
        return f.sent_at + timedelta(days=exp_days), True
    return f.sent_at + timedelta(days=2), False


def _after_link(session: Session, f: _Facts, person_id: UUID, case_id: UUID) -> None:
    """An awaited answer arrived (#5) or an outbound/inbound obligation updated: track waits semantically."""
    case = case_repo.get_case(session, f.company_id, case_id)
    tz = _company_tz(session, f.company_id)
    if f.direction is Direction.inbound:
        extending_promise = (
            f.waiting_side is WaitingSide.third_party
            and not f.requires_reply
            and (f.expected_date is not None or f.expected_days is not None)
        )
        if extending_promise:
            due_at, _ = _resolve_deadline(session, f, case_id=case_id, tz=tz)
            existing = work_repo.active_case_wait(session, f.company_id, case_id, person_id)
            about = f.open_obligation or "Counterparty promised follow-up"
            _transition_via_open(session, f.company_id, case, CaseState.waiting_on_third_party)
            if existing is not None:
                work_repo.reschedule_wait(session, f.company_id, existing.id, expected_by=due_at, about=about)
            else:
                work_repo.open_wait(session, f.company_id, case_id, person_id, about=about, expected_by=due_at)
        else:
            received = work_repo.mark_received(session, f.company_id, case_id, person_id, sent_at=f.sent_at)
            if received and case.state is CaseState.waiting_on_third_party:
                case_repo.transition(session, f.company_id, case_id, CaseState.open, actor="system")
            if f.waiting_side is WaitingSide.third_party and not f.requires_reply and case.state is CaseState.open:
                due_at, _ = _resolve_deadline(session, f, case_id=case_id, tz=tz)
                case_repo.transition(session, f.company_id, case_id, CaseState.waiting_on_third_party, actor="system")
                work_repo.open_wait(
                    session,
                    f.company_id,
                    case_id,
                    person_id,
                    about=f.open_obligation or "Counterparty promised follow-up",
                    expected_by=due_at,
                )
    else:
        if f.waiting_side is WaitingSide.owner:
            due_at, _ = _resolve_deadline(session, f, case_id=case_id, tz=tz)
            _transition_via_open(session, f.company_id, case, CaseState.waiting_on_owner)
            work_repo.record_owner_promise(
                session,
                f.company_id,
                case_id,
                title=f.open_obligation or "Owner follow-up promised",
                due_at=due_at,
            )
        else:
            work_repo.close_case_tasks(session, f.company_id, case_id, source="promise")
            if f.waiting_side is WaitingSide.third_party:
                due_at, explicit = _resolve_deadline(session, f, case_id=case_id, tz=tz, inherit_inbound=True)
                about = f.open_obligation or "Awaiting counterparty update"
                _transition_via_open(session, f.company_id, case, CaseState.waiting_on_third_party)
                existing = work_repo.active_case_wait(session, f.company_id, case_id, person_id)
                if existing is not None and explicit:
                    work_repo.reschedule_wait(session, f.company_id, existing.id, expected_by=due_at, about=about)
                else:
                    work_repo.open_wait(
                        session,
                        f.company_id,
                        case_id,
                        person_id,
                        about=about,
                        expected_by=due_at,
                    )
    if _URGENCY_RANK[f.urgency] > _URGENCY_RANK[case.urgency] or (
        case.urgency is Urgency.high
        and f.urgency in (Urgency.normal, Urgency.low)
        and not f.requires_reply
        and f.waiting_side is WaitingSide.none
        and work_repo.active_case_wait(session, f.company_id, case_id) is None
    ):
        case.urgency = f.urgency
    mark_stale(session, f.company_id, person_id, f.sent_at)


def _refresh_summary(engine: Engine, settings: Settings, f: _Facts, result: LinkResult) -> None:
    with Session(engine) as session:
        case = case_repo.get_case(session, f.company_id, result.case_id)
        previous, version = case.summary, case.summary_version
        label = (
            session.scalar(
                select(Person.display_name).where(Person.company_id == f.company_id, Person.id == result.person_id)
            )
            or f.sender
        )
    prompt = case_summary_prompt(previous, [(f.sent_at, label, f.text)])
    try:
        out = run_agent(
            engine,
            settings,
            CASE_SUMMARY,
            prompt,
            CallContext(f.company_id, "case_summary", message_ids=(f.message_id,)),
        ).output
    except AgentFailedError:
        log.warning("pipeline.case_summary_failed", case_id=str(result.case_id))
        return
    with Session(engine) as session, session.begin():
        summary = f"{out.summary}\nNext: {out.next_step}"
        case_repo.update_summary(session, f.company_id, result.case_id, summary, expected_version=version)


def link_message(engine: Engine, settings: Settings, message_id: UUID) -> LinkResult | None:
    """None for missing messages, spam, and unreadable unknown senders (all understood non-spam mail opens a case)."""
    with Session(engine) as session:
        facts = _load(session, message_id)
    if facts is None or isinstance(facts, LinkResult):
        return facts
    if facts.category is Category.spam or facts.person_id is None or facts.unreadable_stranger:
        return None
    person_id = facts.person_id
    case_id, method = _choose(engine, settings, facts, person_id)
    result = _record(engine, facts, person_id, case_id, method)
    _refresh_summary(engine, settings, facts, result)
    return result

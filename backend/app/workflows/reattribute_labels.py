"""One-time label pass over stored mail (ADR 0016): the sender-role label the inbox shows for a sender the directory
cannot place. One model call for the mail each case shows, never the whole pipeline.

It asks the pinned understanding prompt and keeps only `sender_role`, in `messages.meta.sender_role_pass` (null: no
role). No understanding, case, state or action is written. A mail with the key is never asked again, so a run that
stopped can simply be repeated. Mail flagged suspicious or spam gets no role.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.shown_sender import sender_person_ids
from app.contracts import Category, Channel, Direction, SenderRole
from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import AttachmentRow, CaseLink, LeaseParty, MessageRow, Person, UnderstandingRow
from app.db.models.ingestion import not_chat_only
from app.ingestion.process import company_mailboxes, owner_addresses
from app.llm.agents.understanding import (
    MAX_UNDERSTANDING_BODY_CHARS,
    UNDERSTANDING,
    sees_sender,
    sender_shown_to_model,
    understanding_prompt,
)
from app.llm.calls import CallContext, run_agent
from app.llm.render import AttachmentMeta
from app.pipeline.injection_scan import scan
from app.pipeline.understand import settle_sender_role

log = get_logger(__name__)
LABEL_KEY = "sender_role_pass"
MAX_FAILURES_IN_A_ROW = 5
DEFAULT_MAX_CALLS = 200  # the calls share the daily AI budget with new mail, so one run leaves room for it
_PLACED = (PersonKind.tenant, PersonKind.contractor)  # the directory already labels these


@dataclass
class LabelReport:
    labelled: int = 0  # mails asked and marked, with or without a role
    failed: int = 0
    remaining: int = 0  # candidates this run did not reach
    stopped: str | None = None  # why the pass ended early; run it again to finish


@dataclass(frozen=True)
class _Mail:
    """What choosing needs to know about a message: no body or stored HTML is loaded."""

    id: UUID
    thread_ref: str | None
    channel: Channel
    sender_identity: str
    person_id: UUID | None
    sent_at: datetime
    labelled: bool
    repaired: bool


def _shown_mail(session: Session, company_id: UUID) -> list[_Mail]:
    """The latest incoming message each case shows: among its linked messages and the others of their threads."""
    linked = session.execute(
        select(CaseLink.case_id, MessageRow.id, MessageRow.thread_ref)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(CaseLink.company_id == company_id, MessageRow.company_id == company_id)
    ).all()
    incoming = session.execute(
        select(
            MessageRow.id,
            MessageRow.thread_ref,
            MessageRow.channel,
            MessageRow.sender_identity,
            MessageRow.person_id,
            MessageRow.sent_at,
            MessageRow.meta.has_key(LABEL_KEY),
            MessageRow.meta.has_key("reattributed_from"),
        )
        .where(MessageRow.company_id == company_id, MessageRow.direction == Direction.inbound, not_chat_only())
        .order_by(MessageRow.sent_at, MessageRow.id)
    )
    cases_by_message: dict[UUID, set[UUID]] = {}
    cases_by_thread: dict[str, set[UUID]] = {}
    for case_id, message_id, thread_ref in linked:
        cases_by_message.setdefault(message_id, set()).add(case_id)
        if thread_ref:
            cases_by_thread.setdefault(thread_ref, set()).add(case_id)
    latest: dict[UUID, _Mail] = {}
    for row in incoming:  # oldest first, so the last write per case is its latest
        mail = _Mail(*row)
        cases = cases_by_message.get(mail.id, set()) | cases_by_thread.get(mail.thread_ref or "", set())
        for case_id in cases:
            latest[case_id] = mail
    unique = {mail.id: mail for mail in latest.values()}
    return sorted(unique.values(), key=lambda m: (m.sent_at, m.id))


def _placed_people(session: Session, company_id: UUID, person_ids: set[UUID]) -> set[UUID]:
    if not person_ids:
        return set()
    by_kind = select(Person.id).where(
        Person.company_id == company_id, Person.id.in_(person_ids), Person.kind.in_(_PLACED)
    )
    on_lease = select(LeaseParty.person_id).where(
        LeaseParty.company_id == company_id, LeaseParty.person_id.in_(person_ids)
    )
    return set(session.scalars(by_kind)) | set(session.scalars(on_lease))


def _settled(understanding: UnderstandingRow, repaired: bool) -> bool:
    """Nothing to ask: flagged or spam mail gets no label, and a role found at ingestion stands unless the sender it was
    found for has since been repaired."""
    body = understanding.body if isinstance(understanding.body, dict) else {}
    suspicious = body.get("suspicious")
    if understanding.category is Category.spam or (isinstance(suspicious, dict) and suspicious.get("flag")):
        return True
    return bool(body.get("sender_role")) and not repaired


def label_candidates(session: Session, company_id: UUID) -> list[UUID]:
    """The mails the pass would ask a model about, oldest first."""
    engine: Engine = session.get_bind()  # type: ignore[assignment]
    ours = owner_addresses(engine, company_id) | company_mailboxes(engine, company_id)
    mails = [
        m
        for m in _shown_mail(session, company_id)
        if m.channel is Channel.gmail and not m.labelled and m.sender_identity.lower() not in ours
    ]
    writers = sender_person_ids(session, company_id, mails)
    placed = _placed_people(session, company_id, set(writers.values()))
    understood = {
        u.message_id: u
        for u in session.scalars(
            select(UnderstandingRow).where(
                UnderstandingRow.company_id == company_id, UnderstandingRow.message_id.in_([m.id for m in mails])
            )
        )
    }
    return [
        m.id
        for m in mails
        if writers.get(m.id) not in placed and not (m.id in understood and _settled(understood[m.id], m.repaired))
    ]


def _prompt(session: Session, company_id: UUID, message_id: UUID) -> tuple[str, bool]:
    """The ingestion prompt for one stored mail, and whether the injection scanner flags it."""
    row = session.scalars(
        select(MessageRow).where(MessageRow.company_id == company_id, MessageRow.id == message_id)
    ).one()
    files = session.scalars(
        select(AttachmentRow).where(AttachmentRow.company_id == company_id, AttachmentRow.message_id == message_id)
    )
    subject = (row.meta or {}).get("subject")
    flagged = scan(f"{subject or ''}\n{(row.text or '')[:MAX_UNDERSTANDING_BODY_CHARS]}") is not None
    attachments = [AttachmentMeta(filename=a.filename, mime_type=a.mime_type, size_bytes=a.size_bytes) for a in files]
    prompt = understanding_prompt(
        text=row.text,
        channel=row.channel,
        subject=subject,
        attachments=attachments,
        sender=sender_shown_to_model(row.channel, row.sender_identity),
    )
    return prompt, flagged


def _ask(engine: Engine, settings: Settings, company_id: UUID, message_id: UUID) -> SenderRole | None:
    with Session(engine) as session:
        prompt, flagged = _prompt(session, company_id, message_id)
    context = CallContext(company_id=company_id, purpose="triage")  # same limits as triage at ingestion
    answer = run_agent(engine, settings, UNDERSTANDING, prompt, context).output
    answer = settle_sender_role(answer, prompted=sees_sender(UNDERSTANDING.prompt.version), scanner_flagged=flagged)
    if flagged or answer.suspicious.flag or answer.category is Category.spam:
        return None
    return answer.sender_role


def _store(engine: Engine, company_id: UUID, message_id: UUID, role: SenderRole | None) -> None:
    with Session(engine) as session, session.begin():
        row = session.scalars(
            select(MessageRow).where(MessageRow.company_id == company_id, MessageRow.id == message_id).with_for_update()
        ).one()
        row.meta = {**(row.meta or {}), LABEL_KEY: role.value if role else None}


def label_senders(
    engine: Engine, settings: Settings, company_id: UUID, *, max_calls: int = DEFAULT_MAX_CALLS
) -> LabelReport:
    """Ask once per candidate and store the answer straight away, so nothing already answered is paid for twice."""
    with Session(engine) as session:
        candidates = label_candidates(session, company_id)
    report, in_a_row = LabelReport(), 0
    for message_id in candidates[:max_calls]:
        try:
            _store(engine, company_id, message_id, _ask(engine, settings, company_id, message_id))
        except BudgetExceededError as exc:
            report.stopped = str(exc)
            break
        except Exception as exc:  # one bad mail or a provider hiccup: count it and go on, unless it keeps failing
            log.warning("repair.label_failed", message_id=str(message_id), error_type=type(exc).__name__)
            report.failed, in_a_row = report.failed + 1, in_a_row + 1
            if in_a_row >= MAX_FAILURES_IN_A_ROW:
                report.stopped = f"{in_a_row} model calls failed in a row"
                break
            continue
        report.labelled, in_a_row = report.labelled + 1, 0
    report.remaining = len(candidates) - report.labelled
    return report

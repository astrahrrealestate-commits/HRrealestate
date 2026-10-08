"""Link stage (#3 Context Linking): sender → person, message → case, rolling case summary.

Order: same thread → the person's only open case → `link_check` agent among several open cases → new case.
The model only ever chooses among listed candidates (`accept_link`). A per-person advisory lock serialises the
"new case" decision, so two messages from one sender arriving together never open two cases. Replays return the
existing link unchanged.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.contracts import CaseState, Category, Urgency
from app.core.errors import AgentFailedError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import LinkMethod
from app.db.models import AttachmentRow, CaseLink, MessageRow, Person, UnderstandingRow
from app.llm.agents.case_summary import CASE_SUMMARY, case_summary_prompt
from app.llm.agents.link_check import LINK_CHECK, CandidateCase, accept_link, link_check_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import case_repo, work_repo

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
    category, urgency = (und.category, und.urgency) if und else (Category.other, Urgency.normal)
    if category is Category.spam and (not msg.text.strip() or _has_attachments(session, msg)):
        category = Category.other  # a photo or file with no words is never dropped as spam: Harjot sees it
    return _Facts(msg.id, msg.company_id, msg.person_id, msg.sender_identity, msg.text, msg.sent_at, category, urgency)


def _ask_model(engine: Engine, settings: Settings, f: _Facts, cands: list[CandidateCase]) -> UUID | None:
    prompt = link_check_prompt(f.text, f.category, cands)
    try:
        result = run_agent(engine, settings, LINK_CHECK, prompt, CallContext(f.company_id, "link_check"))
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
        open_cases = case_repo.open_candidates(session, f.company_id, person_id)
    if len(open_cases) == 1:
        return open_cases[0].case_id, LinkMethod.open_case
    if not open_cases:
        return None, LinkMethod.new_case
    cands = [CandidateCase(c.case_id, c.category, c.summary, c.last_message_at) for c in open_cases]
    chosen = _ask_model(engine, settings, f, cands)
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


def _after_link(session: Session, f: _Facts, person_id: UUID, case_id: UUID) -> None:
    """An awaited answer arrived (#5): close the wait, reopen the case. A more urgent message raises urgency."""
    case = case_repo.get_case(session, f.company_id, case_id)
    if work_repo.mark_received(session, f.company_id, case_id, person_id) and (
        case.state is CaseState.waiting_on_third_party
    ):
        case_repo.transition(session, f.company_id, case_id, CaseState.open, actor="system")
    if _URGENCY_RANK[f.urgency] > _URGENCY_RANK[case.urgency]:
        case.urgency = f.urgency


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
        out = run_agent(engine, settings, CASE_SUMMARY, prompt, CallContext(f.company_id, "case_summary")).output
    except AgentFailedError:
        log.warning("pipeline.case_summary_failed", case_id=str(result.case_id))
        return
    with Session(engine) as session, session.begin():
        summary = f"{out.summary}\nNext: {out.next_step}"
        case_repo.update_summary(session, f.company_id, result.case_id, summary, expected_version=version)


def link_message(engine: Engine, settings: Settings, message_id: UUID) -> LinkResult | None:
    """None for missing messages and spam (no case is opened for spam)."""
    with Session(engine) as session:
        facts = _load(session, message_id)
    if facts is None or isinstance(facts, LinkResult):
        return facts
    if facts.category is Category.spam or facts.person_id is None:  # sender resolved by the directory step first
        return None
    person_id = facts.person_id
    case_id, method = _choose(engine, settings, facts, person_id)
    result = _record(engine, facts, person_id, case_id, method)
    _refresh_summary(engine, settings, facts, result)
    return result

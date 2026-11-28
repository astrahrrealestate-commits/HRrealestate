"""Fast-tier outbound triage: understands owner replies synced from Gmail and updates promises/waits/case state."""

from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.message_origin import is_history
from app.contracts import CaseState, Direction, OutboundTriage, WaitingSide
from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import Case, Company, MessageRow, UnderstandingRow
from app.llm.agents.outbound_triage import OUTBOUND_TRIAGE, outbound_triage_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline import case_repo, chasing, work_repo

log = get_logger(__name__)


def _due_from_triage(
    sent_at: datetime,
    expected_date: date | None,
    expected_days: int | None,
    tz: str,
) -> tuple[datetime, bool]:
    local_day = sent_at.astimezone(ZoneInfo(tz)).date()
    if expected_date is not None:
        return chasing.next_morning_after(max(expected_date, local_day), tz), True
    if expected_days is not None:
        return sent_at + timedelta(days=expected_days), True
    return sent_at + timedelta(days=2), False


def apply_outbound_triage(
    session: Session,
    *,
    company_id: UUID,
    case_id: UUID,
    msg: MessageRow,
    triage: OutboundTriage,
) -> None:
    """Apply extracted waiting_side / obligation / resolution onto `case_id`, idempotently."""
    case = case_repo.get_case(session, company_id, case_id)
    if case.state in (CaseState.closed, CaseState.resolved):
        return
    company = session.get(Company, company_id)
    tz = company.timezone if company is not None else chasing.DEFAULT_TZ

    # Only act when this message is the latest (or no newer inbound arrived since).
    if triage.resolved and triage.waiting_side is WaitingSide.none:
        case_repo.close_case_pending(session, company_id, case_id)
        case_repo.transition(session, company_id, case_id, CaseState.resolved, actor="system")
        return

    if triage.waiting_side is WaitingSide.owner:
        due_at, _ = _due_from_triage(msg.sent_at, triage.expected_date, triage.expected_days, tz)
        if case.state is not CaseState.waiting_on_owner:
            if case.state is not CaseState.open:
                case_repo.transition(session, company_id, case_id, CaseState.open, actor="system")
            case_repo.transition(session, company_id, case_id, CaseState.waiting_on_owner, actor="system")
        work_repo.record_owner_promise(
            session,
            company_id,
            case_id,
            title=triage.open_obligation or "Owner follow-up promised",
            due_at=due_at,
        )
        return

    if triage.waiting_side is WaitingSide.third_party:
        work_repo.close_case_tasks(session, company_id, case_id, source="promise")
        if case.primary_person_id is None:
            return
        due_at, explicit = _due_from_triage(msg.sent_at, triage.expected_date, triage.expected_days, tz)
        about = triage.open_obligation or "Awaiting counterparty update"
        if case.state is not CaseState.waiting_on_third_party:
            if case.state is not CaseState.open:
                case_repo.transition(session, company_id, case_id, CaseState.open, actor="system")
            case_repo.transition(session, company_id, case_id, CaseState.waiting_on_third_party, actor="system")
        existing = work_repo.active_case_wait(session, company_id, case_id, case.primary_person_id)
        if existing is not None and explicit:
            work_repo.reschedule_wait(session, company_id, existing.id, expected_by=due_at, about=about)
        elif existing is None:
            work_repo.open_wait(
                session,
                company_id,
                case_id,
                case.primary_person_id,
                about=about,
                expected_by=due_at,
            )


def process_outbound_message(engine: Engine, settings: Settings, message_id: UUID) -> UUID | None:
    """Link an outbound owner reply to its open case, expire stale pending drafts, and extract follow-up state."""
    with Session(engine) as session, session.begin():
        msg = session.get(MessageRow, message_id)
        if msg is None or msg.direction is not Direction.outbound:
            return None
        company_id = msg.company_id
        case_id = case_repo.case_of_message(session, company_id, message_id)
        if case_id is None:
            case_id = case_repo.link_outbound_reply(session, message_id)
        if case_id is None:
            return None
        already = session.scalar(
            select(UnderstandingRow.id).where(
                UnderstandingRow.company_id == company_id,
                UnderstandingRow.message_id == message_id,
            )
        )
        if already is not None:
            return case_id
        if is_history(msg):
            return case_id
        case = session.get(Case, case_id)
        if case is None or case.state in (CaseState.closed, CaseState.resolved):
            return case_id
        subject = msg.meta.get("subject") if isinstance(msg.meta, dict) else None
        prompt = outbound_triage_prompt(
            text=msg.text,
            channel=msg.channel,
            subject=str(subject) if subject else None,
            sent_at=msg.sent_at,
            case_summary=case.summary,
        )

    try:
        res = run_agent(
            engine,
            settings,
            OUTBOUND_TRIAGE,
            prompt,
            CallContext(company_id, "outbound_triage", message_ids=(message_id,)),
        )
        triage = res.output
        model_call_id = res.model_call_id
    except (AgentFailedError, BudgetExceededError) as exc:
        log.warning("pipeline.outbound_triage_skipped", message_id=str(message_id), error=type(exc).__name__)
        return case_id

    with Session(engine) as session, session.begin():
        existing_row = session.scalar(
            select(UnderstandingRow.id).where(
                UnderstandingRow.company_id == company_id,
                UnderstandingRow.message_id == message_id,
            )
        )
        if existing_row is not None:
            return case_id
        reloaded_msg = session.get(MessageRow, message_id)
        reloaded_case = session.get(Case, case_id)
        if reloaded_msg is None or reloaded_case is None:
            return case_id
        session.add(
            UnderstandingRow(
                company_id=company_id,
                message_id=message_id,
                model_call_id=model_call_id,
                category=reloaded_case.category,
                urgency=reloaded_case.urgency,
                body=triage.model_dump(mode="json"),
                prompt_version=triage.prompt_version,
            )
        )
        apply_outbound_triage(
            session,
            company_id=company_id,
            case_id=case_id,
            msg=reloaded_msg,
            triage=triage,
        )
    return case_id

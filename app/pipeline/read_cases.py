"""Case and activity reads for the dashboard API. Every function requires `company_id` (CLAUDE.md invariant 4)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import CaseState
from app.db.enums import CaseEventKind
from app.db.models import ActionRow, Approval, Case, CaseEvent, CaseLink, Outcome, Send
from app.pipeline import case_repo

MAX_TIMELINE = 100
MAX_ACTIONS = 100
MAX_LINKED_MESSAGES = 500


@dataclass(frozen=True)
class CaseBundle:
    case: Case
    timeline: list[CaseEvent]
    message_ids: list[UUID]
    actions: list[tuple[ActionRow, Approval | None]]


@dataclass(frozen=True)
class ActivityRow:
    kind: str
    id: UUID
    at: datetime
    case_id: UUID | None
    action_id: UUID | None
    label: str


def list_cases(session: Session, company_id: UUID, state: CaseState | None, limit: int) -> list[Case]:
    q = select(Case).where(Case.company_id == company_id)
    if state is not None:
        q = q.where(Case.state == state)
    return list(session.scalars(q.order_by(Case.opened_at.desc(), Case.id.desc()).limit(limit)))


def pick_latest(rows: list[Approval]) -> dict[UUID, Approval]:
    """Per action the highest draft_version wins (rows arrive ordered by version, created_at, id)."""
    return {a.action_id: a for a in rows}


def _latest_approvals(session: Session, company_id: UUID, action_ids: list[UUID]) -> dict[UUID, Approval]:
    q = (
        select(Approval)
        .where(Approval.company_id == company_id, Approval.action_id.in_(action_ids))
        .order_by(Approval.draft_version, Approval.created_at, Approval.id)
    )
    return pick_latest(list(session.scalars(q)))


def case_bundle(session: Session, company_id: UUID, case_id: UUID) -> CaseBundle:
    """Raises `NotFoundError` for a missing or foreign case."""
    case = case_repo.get_case(session, company_id, case_id)
    events = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.company_id == company_id, CaseEvent.case_id == case_id)
        .order_by(CaseEvent.created_at.desc(), CaseEvent.id.desc())
        .limit(MAX_TIMELINE)
    ).all()
    message_ids = session.scalars(
        select(CaseLink.message_id)
        .where(CaseLink.company_id == company_id, CaseLink.case_id == case_id)
        .order_by(CaseLink.created_at, CaseLink.id)
        .limit(MAX_LINKED_MESSAGES)
    ).all()
    actions = session.scalars(
        select(ActionRow)
        .where(ActionRow.company_id == company_id, ActionRow.case_id == case_id)
        .order_by(ActionRow.created_at, ActionRow.id)
        .limit(MAX_ACTIONS)
    ).all()
    approvals = _latest_approvals(session, company_id, [a.id for a in actions]) if actions else {}
    return CaseBundle(case, list(reversed(events)), list(message_ids), [(a, approvals.get(a.id)) for a in actions])


def _event_label(kind: CaseEventKind, from_state: CaseState | None, to_state: CaseState | None) -> str:
    """Never the free-text note: it can quote tenant messages."""
    if kind == CaseEventKind.state_change and from_state and to_state:
        return f"state_change: {from_state.value}\u2192{to_state.value}"
    return kind.value


def activity(session: Session, company_id: UUID, limit: int) -> list[ActivityRow]:
    """Newest case events, sends and outcomes merged; each source is capped at `limit` before the merge."""
    events = session.execute(
        select(
            CaseEvent.id,
            CaseEvent.created_at,
            CaseEvent.case_id,
            CaseEvent.kind,
            CaseEvent.from_state,
            CaseEvent.to_state,
        )
        .where(CaseEvent.company_id == company_id)
        .order_by(CaseEvent.created_at.desc(), CaseEvent.id.desc())
        .limit(limit)
    )
    sends = session.execute(
        select(Send.id, Send.created_at, Send.action_id, ActionRow.case_id, Send.channel, Send.status)
        .outerjoin(ActionRow, (ActionRow.id == Send.action_id) & (ActionRow.company_id == company_id))
        .where(Send.company_id == company_id)
        .order_by(Send.created_at.desc(), Send.id.desc())
        .limit(limit)
    )
    outcomes = session.execute(
        select(Outcome.id, Outcome.created_at, Outcome.action_id, ActionRow.case_id, Outcome.label)
        .outerjoin(ActionRow, (ActionRow.id == Outcome.action_id) & (ActionRow.company_id == company_id))
        .where(Outcome.company_id == company_id)
        .order_by(Outcome.created_at.desc(), Outcome.id.desc())
        .limit(limit)
    )
    rows = [ActivityRow("case_event", i, at, cid, None, _event_label(k, f, t)) for i, at, cid, k, f, t in events]
    rows += [ActivityRow("send", i, at, cid, aid, f"{ch.value} {st.value}") for i, at, aid, cid, ch, st in sends]
    rows += [ActivityRow("outcome", i, at, cid, aid, lab.value) for i, at, aid, cid, lab in outcomes]
    return sorted(rows, key=lambda r: (r.at, r.id), reverse=True)[:limit]

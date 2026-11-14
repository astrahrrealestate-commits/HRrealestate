"""Commit-then-crash sweep (every 5 minutes): work whose row committed but whose enqueue never happened.

The API commits first and enqueues second (invariant 1); a crash in between strands an approved action (no
`exec:{action}:{version}` run) or a `pending` Super Agent turn (no `concierge:{turn}` run). The sweep finds them and
re-enqueues under the SAME deterministic workflow id, so a run that exists (queued, running or finished) is never
started twice. Selection is bounded: rows older than `SWEEP_AFTER` (the normal path has enqueued by then) and younger
than `LOOKBACK` (older work is stale; DBOS history is kept for 30 days, so a re-enqueue is always deduped against it),
at most `BATCH` per round. Paused companies' actions are left to `resume`. Anything stranded longer than `LOOKBACK`
is not swept: that needs an operator (docs/dashboard-api.md).

Actions that already have an exec `sends` row are excluded in SQL (NOT EXISTS). Actions whose run DBOS already knows
(a blocked action stays `approved` with no send row) can only be filtered against DBOS, so up to `SCAN` rows are read
and checked before the `BATCH` cut: known runs cannot starve newer stranded ones.

The third kind, tenant sends stuck `sending`, is selected and settled by `app.sender.stuck` (same cron).
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, exists, select
from sqlalchemy.orm import Session

from app.contracts import ActionType
from app.core.workflow_names import concierge_workflow_id, exec_workflow_id
from app.db.enums import ActionStatus, ApprovalStatus, TurnStatus
from app.db.models import ActionRow, AgentTurn, Approval, Company
from app.pipeline.approvals import exec_send
from app.pipeline.local_actions import LOCAL_TYPES

SWEEP_AFTER = timedelta(minutes=5)
LOOKBACK = timedelta(hours=24)
BATCH = 200  # enqueues per round
SCAN = 5 * BATCH  # raw candidates read per round before the DBOS known-id filter
SWEEP_TYPES = frozenset(
    {
        ActionType.reply_draft,
        ActionType.request_contractor,
        ActionType.escalate,
        ActionType.notify_owner,
        ActionType.create_reminder,
        ActionType.update_case_state,
        ActionType.calendar_event,  # decide enqueues exec for every type; the sender blocks what it cannot deliver
    }
)
Stranded = tuple[UUID, int, ActionType]


@dataclass(frozen=True)
class SweepItem:
    kind: str  # "exec" (execute_action_wf) or "turn" (concierge_turn)
    workflow_id: str
    args: tuple[str | int | bool, ...]


def window(now: datetime) -> tuple[datetime, datetime]:
    """(oldest, newest) committed-at bounds of what the sweep may pick up."""
    return now - LOOKBACK, now - SWEEP_AFTER


def plan_sweep(
    actions: Sequence[Stranded], turns: Sequence[UUID], known: Collection[str], limit: int = BATCH
) -> list[SweepItem]:
    """The enqueues of one round: sweepable action types and turns, minus workflow ids DBOS already knows."""
    items = [
        SweepItem("exec", exec_workflow_id(a, v), (str(a), v, t in LOCAL_TYPES))
        for a, v, t in actions
        if t in SWEEP_TYPES
    ]
    items += [SweepItem("turn", concierge_workflow_id(t), (str(t),)) for t in turns]
    return [item for item in items if item.workflow_id not in known][: max(limit, 0)]


def stranded_actions(session: Session, company_id: UUID, now: datetime, limit: int) -> list[Stranded]:
    """Approved, decided in the window, still `approved` (a local action that ran is `executed`), no exec send row."""
    oldest, newest = window(now)
    rows = session.execute(
        select(ActionRow.id, ActionRow.draft_version, ActionRow.type)
        .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.draft_version == ActionRow.draft_version))
        .where(
            ActionRow.company_id == company_id,
            Approval.company_id == company_id,
            ActionRow.status == ActionStatus.approved,
            Approval.status == ApprovalStatus.approved,
            Approval.decided_at >= oldest,
            Approval.decided_at < newest,
            ActionRow.type.in_(SWEEP_TYPES),
            ~exists().where(exec_send(company_id)),
        )
        .order_by(Approval.decided_at)
        .limit(limit)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def stranded_turns(session: Session, company_id: UUID, now: datetime, limit: int) -> list[UUID]:
    oldest, newest = window(now)
    return list(
        session.scalars(
            select(AgentTurn.id)
            .where(
                AgentTurn.company_id == company_id,
                AgentTurn.status == TurnStatus.pending,
                AgentTurn.created_at >= oldest,
                AgentTurn.created_at < newest,
            )
            .order_by(AgentTurn.created_at)
            .limit(limit)
        )
    )


def stranded(engine: Engine, now: datetime, limit: int = BATCH) -> tuple[list[Stranded], list[UUID]]:
    """Per company (every query company-scoped), until `limit` rows in total."""
    actions: list[Stranded] = []
    turns: list[UUID] = []
    with Session(engine) as session:
        for company_id, paused in session.execute(select(Company.id, Company.paused).order_by(Company.id)).all():
            left = limit - len(actions) - len(turns)
            if left <= 0:
                break
            if not paused:
                actions += stranded_actions(session, company_id, now, left)
            turns += stranded_turns(session, company_id, now, limit - len(actions) - len(turns))
    return actions, turns

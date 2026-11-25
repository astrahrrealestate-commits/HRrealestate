"""The draft report (M13 T16): how Harjot treated the drafts, per case category and proposer prompt version.

Counts and ratios only, never message text. It reuses what exists: approvals (approved, rejected, expired, pending),
owner edits (`action_revisions`), the sent-folder labels of `outcomes` (unchanged, edited, rewritten), proposer cost in
`model_calls`, and the owner notice the proposer leaves when every draft was generic. Latency is minutes from the
message being stored to the draft; reloaded history mail is left out of it (`draft-open` drafts it days later).
"""

import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType
from app.db.enums import ApprovalStatus
from app.db.models import ActionRevision, ActionRow, Approval, Case, MessageRow, ModelCall, Outcome

BEFORE_M13 = "before M13"  # actions stored before `actions.prompt_version` existed
NO_USABLE_RATIONALE = "Draft rejected as generic"  # app.pipeline.propose: the notice left instead of a draft


@dataclass
class DraftRow:
    category: str
    prompt_version: str
    offered: int = 0
    approved_unedited: int = 0
    approved_edited: int = 0
    rejected: int = 0
    expired: int = 0
    pending: int = 0
    no_usable: int = 0
    outcomes: dict[str, int] = field(default_factory=dict)
    minutes_p50: float | None = None
    minutes_p90: float | None = None
    _minutes: list[float] = field(default_factory=list, repr=False)


@dataclass(frozen=True)
class DraftReport:
    rows: list[DraftRow]
    cost_usd: dict[str, Decimal]


def _rows(session: Session, company_id: UUID, since: datetime, until: datetime) -> Sequence[tuple[ActionRow, str]]:
    rows = session.execute(
        select(ActionRow, Case.category)
        .join(Case, Case.id == ActionRow.case_id)
        .where(
            ActionRow.company_id == company_id,
            Case.company_id == company_id,
            ActionRow.created_at >= since,
            ActionRow.created_at < until,
            ActionRow.type.in_([ActionType.reply_draft, ActionType.notify_owner]),
        )
    ).all()
    return [(action, category) for action, category in rows]


def _latest_approvals(session: Session, company_id: UUID, ids: list[UUID]) -> dict[UUID, ApprovalStatus]:
    rows = session.execute(
        select(Approval.action_id, Approval.status)
        .where(Approval.company_id == company_id, Approval.action_id.in_(ids))
        .order_by(Approval.created_at, Approval.id)
    )
    latest: dict[UUID, ApprovalStatus] = {}
    for action_id, status in rows:  # in creation order: the last approval wins
        latest[action_id] = status
    return latest


def _owner_edited(session: Session, company_id: UUID, ids: list[UUID]) -> set[UUID]:
    return set(
        session.scalars(
            select(ActionRevision.action_id).where(
                ActionRevision.company_id == company_id,
                ActionRevision.action_id.in_(ids),
                ActionRevision.edited_by.startswith("owner"),
            )
        )
    )


def _outcomes(session: Session, company_id: UUID, ids: list[UUID]) -> dict[UUID, str]:
    rows = session.execute(
        select(Outcome.action_id, Outcome.label).where(Outcome.company_id == company_id, Outcome.action_id.in_(ids))
    )
    return {action_id: label.value for action_id, label in rows}


def _messages(session: Session, company_id: UUID, ids: set[UUID]) -> dict[UUID, tuple[datetime, bool]]:
    rows = session.execute(
        select(MessageRow.id, MessageRow.created_at, MessageRow.meta).where(
            MessageRow.company_id == company_id, MessageRow.id.in_(ids)
        )
    )
    return {mid: (created, (meta or {}).get("history") is True) for mid, created, meta in rows}


def _cost(session: Session, company_id: UUID, since: datetime, until: datetime) -> dict[str, Decimal]:
    rows = session.execute(
        select(ModelCall.prompt_version, func.coalesce(func.sum(ModelCall.cost_usd), 0))
        .where(
            ModelCall.company_id == company_id,
            ModelCall.prompt_name == "proposer",
            ModelCall.created_at >= since,
            ModelCall.created_at < until,
        )
        .group_by(ModelCall.prompt_version)
    )
    return {version: Decimal(total or 0) for version, total in rows}


def _count_reply(row: DraftRow, status: ApprovalStatus | None, edited: bool) -> None:
    row.offered += 1
    if status is ApprovalStatus.approved:
        if edited:
            row.approved_edited += 1
        else:
            row.approved_unedited += 1
    elif status is ApprovalStatus.rejected:
        row.rejected += 1
    elif status is ApprovalStatus.expired:
        row.expired += 1
    else:
        row.pending += 1  # pending, edited and waiting for the new version, or never asked yet


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def draft_report(session: Session, company_id: UUID, *, since: datetime, until: datetime) -> DraftReport:
    actions = _rows(session, company_id, since, until)
    ids = [a.id for a, _ in actions]
    approvals = _latest_approvals(session, company_id, ids)
    edited = _owner_edited(session, company_id, ids)
    labels = _outcomes(session, company_id, ids)
    messages = _messages(session, company_id, {m for a, _ in actions for m in a.context_ref[:1]})
    rows: dict[tuple[str, str], DraftRow] = {}
    for action, category in actions:
        key = (str(getattr(category, "value", category)), action.prompt_version or BEFORE_M13)
        row = rows.setdefault(key, DraftRow(*key))
        if action.type is ActionType.notify_owner:
            row.no_usable += action.rationale == NO_USABLE_RATIONALE
            continue
        _count_reply(row, approvals.get(action.id), action.draft_version > 1 or action.id in edited)
        if action.id in labels:
            row.outcomes = dict(Counter(row.outcomes) + Counter([labels[action.id]]))
        stored = messages.get(action.context_ref[0]) if action.context_ref else None
        if stored is not None and not stored[1]:
            row._minutes.append((action.created_at - stored[0]).total_seconds() / 60)
    for row in rows.values():
        row.minutes_p50, row.minutes_p90 = _percentile(row._minutes, 0.5), _percentile(row._minutes, 0.9)
    kept = sorted((r for r in rows.values() if r.offered or r.no_usable), key=lambda r: (r.category, r.prompt_version))
    return DraftReport(kept, _cost(session, company_id, since, until))


def render_report(report: DraftReport) -> str:
    """A plain table: categories, versions, counts, minutes and cost. No message text exists in a report."""
    head = "category | version | offered | approved unedited | approved edited | rejected | expired | pending | "
    head += "no usable draft | sent outcomes | minutes p50 | minutes p90"
    lines = [head]
    for r in report.rows:
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(r.outcomes.items())) or "-"
        p50 = f"{r.minutes_p50:.1f}" if r.minutes_p50 is not None else "-"
        p90 = f"{r.minutes_p90:.1f}" if r.minutes_p90 is not None else "-"
        lines.append(
            f"{r.category} | {r.prompt_version} | {r.offered} | {r.approved_unedited} | {r.approved_edited} | "
            f"{r.rejected} | {r.expired} | {r.pending} | {r.no_usable} | {outcomes} | {p50} | {p90}"
        )
    lines += [f"proposer cost {version}: USD {total:.4f}" for version, total in sorted(report.cost_usd.items())]
    return "\n".join(lines)

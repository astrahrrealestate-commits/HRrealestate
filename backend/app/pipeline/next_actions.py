"""Category next actions and deterministic briefs (M13 T10).

Ranks existing pipeline and BRIXX items per business category by urgency, due date, waiting age, with ready drafts
(`approve_draft`) and flagged quotes (`quote_review`) first on a tie. Briefs are built strictly from counts.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts import Category, Urgency
from app.contracts.categories import CATEGORY_LABELS, SHOWN_CATEGORIES
from app.contracts.common import Contract
from app.pipeline.next_actions_sources import ActionKind, ActionViewer, NextAction, RankedItem, all_pipeline_items

__all__ = [
    "ActionViewer",
    "BrixxAttentionLike",
    "CategorySummary",
    "NextAction",
    "category_brief",
    "category_summaries",
    "next_actions",
]

_URGENCY_ORDER = {Urgency.emergency: 0, Urgency.high: 1, Urgency.normal: 2, Urgency.low: 3}
_TIE_PRIORITY: dict[ActionKind, int] = {
    "approve_draft": 0,
    "quote_review": 1,
    "reply_needed": 2,
    "overdue_wait": 3,
    "document_review": 4,
    "brixx_ticket": 5,
    "lease_ending": 6,
    "rent_arrears": 7,
}
_BRIXX_CATEGORY: dict[str, Category] = {
    "ticket": Category.maintenance,
    "rent": Category.finance,
    "lease": Category.legal,
}
_BRIXX_KIND: dict[str, ActionKind] = {
    "ticket": "brixx_ticket",
    "rent": "rent_arrears",
    "lease": "lease_ending",
}


class CategorySummary(Contract):
    category: Category
    label: str
    open_actions: int
    urgent: int


@dataclass(frozen=True)
class BrixxAttentionLike:
    id: str
    kind: str  # "ticket" | "rent" | "lease"
    title: str
    detail: str
    unit_label: str
    party_name: str
    urgent: bool
    age_days: int
    href: str


def _brixx_ranked(items: Sequence[BrixxAttentionLike], viewer: ActionViewer, now: datetime) -> list[RankedItem]:
    out: list[RankedItem] = []
    for item in items:
        if item.kind == "rent" and not viewer.money:
            continue
        cat = _BRIXX_CATEGORY.get(item.kind)
        kind = _BRIXX_KIND.get(item.kind)
        if cat is None or kind is None:
            continue
        who = viewer.party(item.party_name, "")
        where = " · ".join(p for p in (item.unit_label, who, item.detail) if p)
        due_at = (now + timedelta(days=item.age_days)) if item.kind == "lease" else None
        created = now - timedelta(days=item.age_days)
        out.append(
            RankedItem(
                NextAction(
                    id=f"brixx:{item.id}",
                    category=cat,
                    kind=kind,
                    title=item.title,
                    why=where,
                    urgency=Urgency.high if item.urgent else Urgency.normal,
                    due_at=due_at,
                    case_id=None,
                    approval_id=None,
                    prepared=None,
                    target_url=item.href,
                ),
                created,
            )
        )
    return out


def _rank_key(item: RankedItem) -> tuple[int, int, float, int, float, str]:
    a = item.action
    has_due = 0 if a.due_at is not None else 1
    due_ts = a.due_at.timestamp() if a.due_at is not None else 0.0
    return (
        _URGENCY_ORDER[a.urgency],
        has_due,
        due_ts,
        _TIE_PRIORITY[a.kind],
        item.created_at.timestamp(),
        a.id,
    )


def _gather(
    session: Session, company_id: UUID, viewer: ActionViewer, brixx_items: Sequence[BrixxAttentionLike], now: datetime
) -> list[RankedItem]:  # fmt: skip
    items = [*all_pipeline_items(session, company_id, viewer, now), *_brixx_ranked(brixx_items, viewer, now)]
    return sorted(items, key=_rank_key)


def next_actions(
    session: Session,
    company_id: UUID,
    category: Category,
    viewer: ActionViewer,
    limit: int = 15,
    *,
    brixx_items: Sequence[BrixxAttentionLike] = (),
    now: datetime | None = None,
) -> list[NextAction]:
    """Ranked next actions for one of the six categories; empty list for `spam`."""
    if category not in SHOWN_CATEGORIES:
        return []
    ref = now or datetime.now(UTC)
    ranked = [
        item.action
        for item in _gather(session, company_id, viewer, brixx_items, ref)
        if item.action.category is category
    ]
    return ranked[: max(1, limit)]


def category_summaries(
    session: Session,
    company_id: UUID,
    viewer: ActionViewer,
    *,
    brixx_items: Sequence[BrixxAttentionLike] = (),
    now: datetime | None = None,
) -> list[CategorySummary]:
    """Counts per category in display order for the Today category tabs."""
    ref = now or datetime.now(UTC)
    items = _gather(session, company_id, viewer, brixx_items, ref)
    total: Counter[Category] = Counter()
    urgent: Counter[Category] = Counter()
    for item in items:
        cat = item.action.category
        total[cat] += 1
        if item.action.urgency in (Urgency.emergency, Urgency.high):
            urgent[cat] += 1
    return [
        CategorySummary(category=cat, label=CATEGORY_LABELS[cat], open_actions=total[cat], urgent=urgent[cat])
        for cat in SHOWN_CATEGORIES
    ]


_PHRASES: tuple[tuple[ActionKind, str, str], ...] = (
    ("quote_review", "1 quote above market", "{n} quotes above market"),
    ("approve_draft", "1 reply ready to approve", "{n} replies ready to approve"),
    ("reply_needed", "1 message awaiting reply", "{n} messages awaiting reply"),
    ("overdue_wait", "1 overdue follow-up", "{n} overdue follow-ups"),
    ("document_review", "1 document to review", "{n} documents to review"),
    ("brixx_ticket", "1 open BRIXX ticket", "{n} open BRIXX tickets"),
    ("rent_arrears", "1 rent arrears case", "{n} rent arrears cases"),
    ("lease_ending", "1 lease ending soon", "{n} leases ending soon"),
)


def category_brief(actions: Sequence[NextAction]) -> str | None:
    """One sentence built strictly from action counts; None when nothing needs doing."""
    if not actions:
        return None
    counts = Counter(a.kind for a in actions)
    parts = [
        (one if counts[kind] == 1 else many.format(n=counts[kind])) for kind, one, many in _PHRASES if counts[kind]
    ]
    return ", ".join(parts[:3]) + "." if parts else None

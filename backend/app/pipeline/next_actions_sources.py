"""Approval and reply-needed loaders for category next actions (M13 T10). Every query filters by `company_id`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.message_origin import is_owner_authored
from app.contracts import ActionType, CaseState, Category, Direction, Urgency
from app.contracts.categories import current_category
from app.db.enums import ActionStatus, ApprovalStatus, TaskStatus, WaitStatus
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseLink,
    MessageRow,
    Person,
    TaskRow,
    UnderstandingRow,
    Unit,
    WaitRow,
)
from app.db.models.ingestion import not_chat_only
from app.pipeline.next_actions_items import (
    OPEN_STATES,
    ActionKind,
    ActionViewer,
    NextAction,
    as_utc,
    load_document_reviews,
    load_overdue_waits,
    load_quote_reviews,
    one_line,
)

__all__ = [
    "ActionKind",
    "ActionViewer",
    "NextAction",
    "RankedItem",
    "all_pipeline_items",
    "enrich_actions",
    "waiting_split",
]


@dataclass(frozen=True)
class RankedItem:
    action: NextAction
    created_at: datetime


def _first_draft_line(payload: dict[str, object]) -> str | None:
    variants = payload.get("body_variants")
    if isinstance(variants, list) and variants and isinstance(variants[0], str):
        first = one_line(variants[0], 180)
        return first or None
    return None


def load_approvals(session: Session, company_id: UUID, viewer: ActionViewer) -> list[RankedItem]:
    rows = session.execute(
        select(Approval, ActionRow, Case, Person.display_name)
        .join(ActionRow, (ActionRow.id == Approval.action_id) & (ActionRow.company_id == company_id))
        .join(Case, (Case.id == ActionRow.case_id) & (Case.company_id == company_id))
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            ActionRow.type == ActionType.reply_draft,
            ActionRow.status != ActionStatus.rejected,
        )
    ).all()
    out: list[RankedItem] = []
    for approval, action, case, name in rows:
        cat = current_category(case.category.value)
        if cat is Category.spam:
            continue
        party = viewer.party(name)
        why = (one_line(case.summary) if viewer.inbox else "") or "Reply draft ready for approval"
        prepared = _first_draft_line(action.payload) if viewer.inbox else None
        out.append(
            RankedItem(
                NextAction(
                    id=f"approval:{approval.id}",
                    category=cat,
                    kind="approve_draft",
                    title=f"Approve reply to {party}",
                    why=why,
                    urgency=case.urgency,
                    due_at=None,
                    case_id=case.id,
                    approval_id=approval.id,
                    prepared=prepared,
                    target_url=f"/inbox?thread={case.id}",
                ),
                as_utc(approval.created_at),
            )
        )
    return out


def load_replies_needed(session: Session, company_id: UUID, viewer: ActionViewer) -> list[RankedItem]:
    live_cases = set(
        session.scalars(
            select(ActionRow.case_id)
            .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.company_id == company_id))
            .where(
                Approval.company_id == company_id,
                Approval.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
                ActionRow.type == ActionType.reply_draft,
            )
        ).all()
    )
    cases = list(
        session.execute(
            select(Case, Person.display_name)
            .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
            .where(Case.company_id == company_id, Case.state.in_(OPEN_STATES))
        ).all()
    )
    out: list[RankedItem] = []
    for case, name in cases:
        cat = current_category(case.category.value)
        if cat is Category.spam or case.id in live_cases:
            continue
        newest = session.scalar(
            select(MessageRow)
            .join(CaseLink, (CaseLink.message_id == MessageRow.id) & (CaseLink.company_id == company_id))
            .where(CaseLink.company_id == company_id, CaseLink.case_id == case.id, not_chat_only())
            .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
            .limit(1)
        )
        if newest is None or newest.direction is Direction.outbound or is_owner_authored(newest):
            continue
        body = session.scalar(
            select(UnderstandingRow.body).where(
                UnderstandingRow.company_id == company_id, UnderstandingRow.message_id == newest.id
            )
        )
        if not (isinstance(body, dict) and body.get("requires_reply")):
            continue
        party = viewer.party(name)
        why = (one_line(case.summary) if viewer.inbox else "") or "Inbound message awaiting reply"
        out.append(
            RankedItem(
                NextAction(
                    id=f"reply:{case.id}",
                    category=cat,
                    kind="reply_needed",
                    title=f"Reply needed · {party}",
                    why=why,
                    urgency=case.urgency,
                    due_at=None,
                    case_id=case.id,
                    approval_id=None,
                    prepared="Draft with Astra" if viewer.inbox else None,
                    target_url=f"/inbox?thread={case.id}",
                ),
                as_utc(newest.sent_at),
            )
        )
    return out


def all_pipeline_items(
    session: Session, company_id: UUID, viewer: ActionViewer, now: datetime
) -> Sequence[RankedItem]:  # fmt: skip
    extra = [
        *load_quote_reviews(session, company_id, viewer),
        *load_overdue_waits(session, company_id, viewer, now),
        *load_document_reviews(session, company_id, viewer),
    ]
    return [
        *load_approvals(session, company_id, viewer),
        *load_replies_needed(session, company_id, viewer),
        *(RankedItem(action, ts) for action, ts in extra),
    ]


def _case_meta_map(
    session: Session, company_id: UUID, viewer: ActionViewer, case_ids: Sequence[UUID]
) -> dict[UUID, dict[str, object]]:
    """Batch-load unit label, sender name, channel, subject and last timestamp for a set of cases."""
    unique_ids = list({cid for cid in case_ids if cid is not None})
    if not unique_ids:
        return {}
    case_rows = session.execute(
        select(Case.id, Person.display_name, Unit.address, Unit.label)
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .outerjoin(Unit, (Unit.id == Case.unit_id) & (Unit.company_id == company_id))
        .where(Case.company_id == company_id, Case.id.in_(unique_ids))
    ).all()
    meta: dict[UUID, dict[str, object]] = {
        cid: {
            "sender_name": viewer.party(pname),
            "unit_label": (addr or ulabel or "") if (addr or ulabel) else None,
            "channel": None,
            "subject": None,
            "last_at": None,
        }
        for cid, pname, addr, ulabel in case_rows
    }
    msgs = session.execute(
        select(CaseLink.case_id, MessageRow.channel, MessageRow.sent_at, MessageRow.meta)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id.in_(unique_ids),
            MessageRow.company_id == company_id,
            not_chat_only(),
        )
        .order_by(CaseLink.case_id, MessageRow.sent_at.desc(), MessageRow.id.desc())
    ).all()
    for cid, ch, sent_at, msg_meta in msgs:
        entry = meta.get(cid)
        if entry is None or entry["last_at"] is not None:
            continue
        subj = msg_meta.get("subject") if isinstance(msg_meta, dict) else None
        entry["channel"] = ch.value if ch else "gmail"
        entry["subject"] = str(subj)[:160] if subj else None
        entry["last_at"] = as_utc(sent_at)
    return meta


def enrich_actions(
    session: Session, company_id: UUID, viewer: ActionViewer, actions: Sequence[NextAction], *, now: datetime
) -> list[NextAction]:
    """Attach channel, sender, unit, subject, and age metadata to ranked actions in a single batch query."""
    if not actions:
        return []
    meta = _case_meta_map(
        session, company_id, viewer, [a.case_id for a in actions if a.case_id is not None]
    )
    ref = as_utc(now)
    out: list[NextAction] = []
    for act in actions:
        m = meta.get(act.case_id) if act.case_id is not None else None
        last_at = m["last_at"] if m else act.due_at
        wait_days = act.waiting_days
        if wait_days is None and isinstance(last_at, datetime):
            wait_days = max(0, (ref - as_utc(last_at)).days)
        updates: dict[str, object] = {
            "has_draft": act.has_draft or act.kind == "approve_draft" or act.approval_id is not None,
        }
        if m is not None:
            if not act.channel and m["channel"] is not None:
                updates["channel"] = m["channel"]
            if not act.sender_name and m["sender_name"] is not None:
                updates["sender_name"] = m["sender_name"]
            if not act.unit_label and m["unit_label"] is not None:
                updates["unit_label"] = m["unit_label"]
            if not act.subject and m["subject"] is not None:
                updates["subject"] = m["subject"]
            if act.last_at is None and m["last_at"] is not None:
                updates["last_at"] = m["last_at"]
        if act.waiting_days is None and wait_days is not None:
            updates["waiting_days"] = wait_days
        out.append(act.model_copy(update=updates))
    return out


def waiting_split(
    session: Session,
    company_id: UUID,
    category: Category,
    viewer: ActionViewer,
    *,
    now: datetime | None = None,
    limit: int = 20,
) -> tuple[list[NextAction], list[NextAction]]:
    """Split open threads in `category` into `(waiting_for_us, waiting_for_other)` without duplicate cases."""
    ref = as_utc(now or datetime.now(UTC))
    cases = list(
        session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.state.in_(OPEN_STATES))
            .order_by(Case.opened_at.desc())
        ).all()
    )
    cat_cases = [c for c in cases if current_category(c.category.value) is category]
    if not cat_cases:
        return [], []
    cat_ids = [c.id for c in cat_cases]

    open_promises: dict[UUID, TaskRow] = {}
    for t in session.scalars(
        select(TaskRow).where(
            TaskRow.company_id == company_id,
            TaskRow.case_id.in_(cat_ids),
            TaskRow.assignee == "owner",
            TaskRow.source.in_(["promise", "reminder"]),
            TaskRow.status.in_([TaskStatus.open, TaskStatus.snoozed]),
        )
    ).all():
        if t.case_id is not None and t.case_id not in open_promises:
            open_promises[t.case_id] = t

    active_waits: dict[UUID, WaitRow] = {}
    for w in session.scalars(
        select(WaitRow).where(
            WaitRow.company_id == company_id,
            WaitRow.case_id.in_(cat_ids),
            WaitRow.status == WaitStatus.waiting,
        )
    ).all():
        if w.case_id not in active_waits:
            active_waits[w.case_id] = w

    pending_approvals = set(
        session.scalars(
            select(ActionRow.case_id)
            .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.company_id == company_id))
            .where(
                Approval.company_id == company_id,
                Approval.status == ApprovalStatus.pending,
                ActionRow.company_id == company_id,
                ActionRow.case_id.in_(cat_ids),
                ActionRow.type == ActionType.reply_draft,
            )
        ).all()
    )

    latest_msgs: dict[UUID, MessageRow] = {}
    for msg_cid, msg in session.execute(
        select(CaseLink.case_id, MessageRow)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id.in_(cat_ids),
            MessageRow.company_id == company_id,
            not_chat_only(),
        )
        .order_by(CaseLink.case_id, MessageRow.sent_at.desc(), MessageRow.id.desc())
    ).all():
        if msg_cid not in latest_msgs:
            latest_msgs[msg_cid] = msg

    und_by_msg: dict[UUID, dict[str, object]] = {}
    if latest_msgs:
        for mid, body in session.execute(
            select(UnderstandingRow.message_id, UnderstandingRow.body).where(
                UnderstandingRow.company_id == company_id,
                UnderstandingRow.message_id.in_([m.id for m in latest_msgs.values()]),
            )
        ).all():
            if isinstance(body, dict):
                und_by_msg[mid] = body

    urg_rank = {Urgency.emergency: 0, Urgency.high: 1, Urgency.normal: 2, Urgency.low: 3}
    for_us: list[tuple[tuple[int, int, float], NextAction]] = []
    for_other: list[tuple[tuple[int, int, float], NextAction]] = []

    for c in cat_cases:
        promise = open_promises.get(c.id)
        wait = active_waits.get(c.id)
        newest = latest_msgs.get(c.id)
        body = und_by_msg.get(newest.id, {}) if newest is not None else {}
        requires_reply = body.get("requires_reply", True) if body else True
        has_draft = c.id in pending_approvals
        last_at = as_utc(newest.sent_at) if newest is not None else as_utc(c.opened_at)
        days = max(0, (ref - last_at).days)

        is_our_obligation = (
            promise is not None
            or c.state is CaseState.waiting_on_owner
            or has_draft
            or (
                c.state is CaseState.open
                and newest is not None
                and newest.direction is Direction.inbound
                and not is_owner_authored(newest)
                and requires_reply is not False
            )
        )
        is_their_obligation = (
            not is_our_obligation
            and (
                wait is not None
                or c.state is CaseState.waiting_on_third_party
                or (newest is not None and (newest.direction is Direction.outbound or is_owner_authored(newest)))
            )
        )

        if is_our_obligation:
            ob_text = promise.title if promise is not None else (
                str(body.get("open_obligation")) if isinstance(body.get("open_obligation"), str) else None
            )
            why_text = ob_text or (one_line(c.summary) if viewer.inbox else "") or "Awaiting our response"
            action = NextAction(
                id=f"wait-us:{c.id}",
                category=category,
                kind="approve_draft" if has_draft else "reply_needed",
                title=ob_text or ("Draft ready to send" if has_draft else "Reply / follow-up needed"),
                why=why_text,
                urgency=c.urgency,
                due_at=as_utc(promise.due_at) if promise and promise.due_at else None,
                case_id=c.id,
                approval_id=None,
                prepared=None,
                target_url=f"/inbox?thread={c.id}",
                waiting_side="owner",
                waiting_days=days,
                obligation=ob_text,
                has_draft=has_draft,
                last_at=last_at,
            )
            has_promise_priority = 0 if (promise is not None or c.state is CaseState.waiting_on_owner) else 1
            for_us.append(((has_promise_priority, urg_rank.get(c.urgency, 2), -days), action))
        elif is_their_obligation:
            wait_days = max(0, (ref - as_utc(wait.created_at)).days) if wait is not None else days
            ob_text = wait.about if wait is not None else (
                str(body.get("open_obligation")) if isinstance(body.get("open_obligation"), str) else None
            )
            why_text = (ob_text if viewer.inbox or wait else "") or f"Waiting {wait_days}d for update"
            overdue = 0 if (wait is not None and as_utc(wait.expected_by) <= ref) else 1
            action = NextAction(
                id=f"wait-other:{c.id}",
                category=category,
                kind="overdue_wait",
                title=ob_text or "Awaiting their update",
                why=why_text,
                urgency=c.urgency,
                due_at=as_utc(wait.expected_by) if wait is not None else None,
                case_id=c.id,
                approval_id=None,
                prepared=None,
                target_url=f"/inbox?thread={c.id}",
                waiting_side="third_party",
                waiting_days=wait_days,
                obligation=ob_text,
                has_draft=False,
                last_at=last_at,
            )
            for_other.append(((overdue, urg_rank.get(c.urgency, 2), -wait_days), action))

    for_us.sort(key=lambda pair: pair[0])
    for_other.sort(key=lambda pair: pair[0])
    us_enriched = enrich_actions(session, company_id, viewer, [a for _, a in for_us[:limit]], now=ref)
    other_enriched = enrich_actions(session, company_id, viewer, [a for _, a in for_other[:limit]], now=ref)
    return us_enriched, other_enriched

"""Approval and reply-needed loaders for category next actions (M13 T10). Every query filters by `company_id`."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
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
    Company,
    MessageRow,
    Person,
    TaskRow,
    UnderstandingRow,
    Unit,
    WaitRow,
)
from app.db.models.ingestion import not_chat_only
from app.pipeline import chasing
from app.pipeline.next_actions_items import (
    OPEN_STATES,
    ActionKind,
    ActionViewer,
    NextAction,
    as_utc,
    load_document_reviews,
    load_overdue_waits,
    load_quote_reviews,
    matches_period,
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
    "waiting_split_page",
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
            Case.state.in_(OPEN_STATES),
        )
    ).all()
    case_ids = [case.id for _, _, case, _ in rows]
    newest_of = _newest_per_case(session, company_id, case_ids) if case_ids else {}
    out: list[RankedItem] = []
    for approval, action, case, name in rows:
        cat = current_category(case.category.value)
        if cat is Category.spam:
            continue
        newest_pair = newest_of.get(case.id)
        if newest_pair is not None:
            newest_msg = newest_pair[0]
            newest_at = as_utc(newest_msg.sent_at)
            if (newest_msg.direction is Direction.outbound or is_owner_authored(newest_msg)) and newest_at >= as_utc(
                approval.created_at
            ):
                continue
            item_ts = newest_at
        else:
            item_ts = as_utc(approval.created_at)
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
                    last_at=item_ts,
                ),
                item_ts,
            )
        )
    return out


def _newest_per_case(session: Session, company_id: UUID, case_ids: list[UUID]) -> dict[UUID, tuple[MessageRow, object]]:
    """Each case's newest message (chat-only mail left out) with its understanding, in one query."""
    if not case_ids:
        return {}
    rows = session.execute(
        select(CaseLink.case_id, MessageRow, UnderstandingRow.body)
        .join(MessageRow, (MessageRow.id == CaseLink.message_id) & (MessageRow.company_id == company_id))
        .outerjoin(
            UnderstandingRow,
            (UnderstandingRow.message_id == MessageRow.id) & (UnderstandingRow.company_id == company_id),
        )
        .where(CaseLink.company_id == company_id, CaseLink.case_id.in_(case_ids), not_chat_only())
        .order_by(CaseLink.case_id, MessageRow.sent_at.desc(), MessageRow.id.desc())
        .ext(distinct_on(CaseLink.case_id))
    ).all()
    return {case_id: (message, body) for case_id, message, body in rows}


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
    wanted = [
        c.id for c, _ in cases if c.id not in live_cases and current_category(c.category.value) is not Category.spam
    ]
    newest_of = _newest_per_case(session, company_id, wanted)
    out: list[RankedItem] = []
    for case, name in cases:
        cat = current_category(case.category.value)
        if case.id not in newest_of:
            continue
        newest, body = newest_of[case.id]
        if newest.direction is Direction.outbound or is_owner_authored(newest):
            continue
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
                    last_at=as_utc(newest.sent_at),
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
    meta = _case_meta_map(session, company_id, viewer, [a.case_id for a in actions if a.case_id is not None])
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
    urgency_filter: Literal["all", "emergency", "high", "low", "urgent"] = "all",
    sort: Literal["priority", "latest"] = "priority",
    period: str = "all",
) -> tuple[list[NextAction], list[NextAction]]:
    """Split open commitments & waits in `category` into `(waiting_for_us, waiting_for_other)` without duplicates."""
    us, other, _, _ = waiting_split_page(
        session,
        company_id,
        category,
        viewer,
        now=now,
        limit=limit,
        urgency_filter=urgency_filter,
        sort=sort,
        period=period,
    )
    return us, other


def waiting_split_page(
    session: Session,
    company_id: UUID,
    category: Category,
    viewer: ActionViewer,
    *,
    now: datetime | None = None,
    limit: int = 20,
    urgency_filter: Literal["all", "emergency", "high", "low", "urgent"] = "all",
    sort: Literal["priority", "latest"] = "priority",
    period: str = "all",
) -> tuple[list[NextAction], list[NextAction], int, int]:
    """Split true owner promises & active third-party waits into `(us, other, us_total, other_total)`."""
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
        return [], [], 0, 0
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
        select(WaitRow)
        .where(
            WaitRow.company_id == company_id,
            WaitRow.case_id.in_(cat_ids),
            WaitRow.status.in_([WaitStatus.waiting, WaitStatus.escalated]),
        )
        .order_by(WaitRow.expected_by, WaitRow.id)
    ).all():
        if w.case_id not in active_waits:
            active_waits[w.case_id] = w

    company_row = session.get(Company, company_id)
    tz = company_row.timezone if company_row is not None else chasing.DEFAULT_TZ

    pending_approvals: dict[UUID, UUID] = {}
    for app_case_id, app_id in session.execute(
        select(ActionRow.case_id, Approval.id)
        .join(Approval, (Approval.action_id == ActionRow.id) & (Approval.company_id == company_id))
        .where(
            Approval.company_id == company_id,
            Approval.status == ApprovalStatus.pending,
            ActionRow.company_id == company_id,
            ActionRow.case_id.in_(cat_ids),
            ActionRow.type.in_([ActionType.reply_draft, ActionType.request_contractor, ActionType.escalate]),
        )
        .order_by(Approval.created_at.desc(), Approval.id.desc())
    ).all():
        if app_case_id not in pending_approvals:
            pending_approvals[app_case_id] = app_id

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
    for_us: list[tuple[tuple[object, ...], NextAction]] = []
    for_other: list[tuple[tuple[object, ...], NextAction]] = []

    for c in cat_cases:
        if urgency_filter == "emergency" and c.urgency is not Urgency.emergency:
            continue
        if urgency_filter == "high" and c.urgency is not Urgency.high:
            continue
        if urgency_filter == "low" and c.urgency not in (Urgency.normal, Urgency.low):
            continue
        if urgency_filter == "urgent" and c.urgency not in (Urgency.emergency, Urgency.high):
            continue
        promise = open_promises.get(c.id)
        wait = active_waits.get(c.id)
        newest = latest_msgs.get(c.id)
        body = und_by_msg.get(newest.id, {}) if newest is not None else {}
        approval_id = pending_approvals.get(c.id)
        has_draft = approval_id is not None
        last_at = as_utc(newest.sent_at) if newest is not None else as_utc(c.opened_at)
        if not matches_period(last_at, period, ref, tz):
            continue
        days = max(0, (ref - last_at).days)

        # True owner promises only (never duplicate every unanswered inbound email from the main list).
        is_our_obligation = promise is not None or c.state is CaseState.waiting_on_owner
        # Genuine awaited deliverables only (active wait or waiting_on_third_party).
        is_their_obligation = not is_our_obligation and (
            wait is not None or c.state is CaseState.waiting_on_third_party
        )

        if is_our_obligation:
            ob_text = (
                promise.title
                if promise is not None
                else (str(body.get("open_obligation")) if isinstance(body.get("open_obligation"), str) else None)
            )
            why_text = ob_text or (one_line(c.summary) if viewer.inbox else "") or "Awaiting our response"
            due_at = as_utc(promise.due_at) if promise and promise.due_at else None
            overdue_days = chasing.overdue_days_from(due_at, ref, tz) if due_at is not None else 0
            action = NextAction(
                id=f"wait-us:{c.id}",
                category=category,
                kind="approve_draft" if has_draft else "reply_needed",
                title=ob_text or ("Draft ready to send" if has_draft else "Promise / follow-up needed"),
                why=why_text,
                urgency=c.urgency,
                due_at=due_at,
                case_id=c.id,
                approval_id=approval_id,
                prepared="Draft ready to approve" if has_draft else None,
                target_url=f"/inbox?thread={c.id}",
                waiting_side="owner",
                waiting_days=days,
                obligation=ob_text,
                has_draft=has_draft,
                last_at=last_at,
                overdue_days=overdue_days,
                chase_count=0,
                wait_status="promise" if promise is not None else None,
            )
            us_key: tuple[object, ...] = (
                (-last_at.timestamp(),)
                if sort == "latest"
                else (
                    0 if overdue_days > 0 else 1,
                    0 if (promise is not None or c.state is CaseState.waiting_on_owner) else 1,
                    -overdue_days,
                    urg_rank.get(c.urgency, 2),
                    -last_at.timestamp(),
                )
            )
            for_us.append((us_key, action))
        elif is_their_obligation:
            wait_days = max(0, (ref - as_utc(wait.created_at)).days) if wait is not None else days
            ob_text = (
                wait.about
                if wait is not None
                else (str(body.get("open_obligation")) if isinstance(body.get("open_obligation"), str) else None)
            )
            why_text = (ob_text if viewer.inbox or wait else "") or f"Waiting {wait_days}d for update"
            due_at = as_utc(wait.expected_by) if wait is not None else None
            overdue_days = chasing.overdue_days_from(due_at, ref, tz) if due_at is not None else 0
            if wait is not None and wait.status is WaitStatus.escalated:
                w_status: Literal["waiting", "chased", "escalated", "promise"] = "escalated"
            elif wait is not None and wait.chase_count > 0:
                w_status = "chased"
            else:
                w_status = "waiting"
            tier = 0 if w_status == "escalated" else (1 if overdue_days > 0 else 2)
            action = NextAction(
                id=f"wait-other:{c.id}",
                category=category,
                kind="overdue_wait",
                title=ob_text or "Awaiting their update",
                why=why_text,
                urgency=c.urgency,
                due_at=due_at,
                case_id=c.id,
                approval_id=approval_id,
                prepared="Chaser draft ready" if has_draft else None,
                target_url=f"/inbox?thread={c.id}",
                waiting_side="third_party",
                waiting_days=wait_days,
                obligation=ob_text,
                has_draft=has_draft,
                last_at=last_at,
                overdue_days=overdue_days,
                chase_count=wait.chase_count if wait is not None else 0,
                wait_status=w_status,
                wait_id=wait.id if wait is not None else None,
            )
            other_key: tuple[object, ...] = (
                (-last_at.timestamp(),)
                if sort == "latest"
                else (tier, -overdue_days, urg_rank.get(c.urgency, 2), -last_at.timestamp())
            )
            for_other.append((other_key, action))

    for_us.sort(key=lambda pair: pair[0])
    for_other.sort(key=lambda pair: pair[0])
    us_total = len(for_us)
    other_total = len(for_other)
    us_enriched = enrich_actions(session, company_id, viewer, [a for _, a in for_us[:limit]], now=ref)
    other_enriched = enrich_actions(session, company_id, viewer, [a for _, a in for_other[:limit]], now=ref)
    return us_enriched, other_enriched, us_total, other_total

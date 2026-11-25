"""Short labels for the row ids a dashboard page shows (`PageContext.visible_ids`), company-scoped (invariant 4).

One bounded query per kind (cases, approvals, documents, tasks by id, tasks by ref, threads). Ids that do not belong
to the company get no label and are only counted, so another company's rows never reach the prompt.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.contracts.page_context import MAX_VISIBLE, VisibleKind, visible_kind
from app.db.models import ActionRow, Approval, AttachmentRow, Case, MessageRow, Person, TaskRow
from app.db.models.ingestion import not_chat_only
from app.pipeline.read_repo import decode_thread_key, encode_thread_key
from app.pipeline.work_repo import short_ref

MAX_LABEL = 120
UNKNOWN_SENDER = "Unknown sender"


def _line(value: str) -> str:
    return " ".join(value.split())[:MAX_LABEL]


def _cases(session: Session, company_id: UUID, ids: Sequence[UUID]) -> dict[str, str]:
    rows = session.execute(
        select(Case.id, Case.category, Case.state, Person.display_name)
        .outerjoin(Person, (Person.id == Case.primary_person_id) & (Person.company_id == company_id))
        .where(Case.company_id == company_id, Case.id.in_(ids))
        .limit(MAX_VISIBLE)
    ).all()
    return {
        str(i): _line(f"case {i} | {name or UNKNOWN_SENDER} · {cat.value} | {state.value}")
        for i, cat, state, name in rows
    }


def _approvals(session: Session, company_id: UUID, ids: Sequence[UUID]) -> dict[str, str]:
    rows = session.execute(
        select(Approval.id, Approval.status, ActionRow.type, ActionRow.case_id)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(Approval.company_id == company_id, ActionRow.company_id == company_id, Approval.id.in_(ids))
        .limit(MAX_VISIBLE)
    ).all()
    return {str(i): f"approval {i} | {kind.value} | {status.value} | case {case}" for i, status, kind, case in rows}


def _documents(session: Session, company_id: UUID, ids: Sequence[UUID]) -> dict[str, str]:
    rows = session.execute(
        select(AttachmentRow.id, AttachmentRow.filename)
        .where(AttachmentRow.company_id == company_id, AttachmentRow.id.in_(ids))
        .limit(MAX_VISIBLE)
    ).all()
    return {str(i): _line(f"document {i} | {name or 'unnamed'}") for i, name in rows}


def _task_label(task: TaskRow) -> str:
    return _line(f"task #{short_ref(task.id)} | {task.title} | {task.status.value}")


def _tasks_by_id(session: Session, company_id: UUID, ids: Sequence[UUID]) -> dict[str, str]:
    q = select(TaskRow).where(TaskRow.company_id == company_id, TaskRow.id.in_(ids)).limit(MAX_VISIBLE)
    return {str(t.id): _task_label(t) for t in session.scalars(q)}


def _tasks_by_ref(session: Session, company_id: UUID, refs: Sequence[str]) -> dict[str, str]:
    """Refs are validated hex (no LIKE wildcards); a ref matching more than one task gets no label."""
    q = (
        select(TaskRow)
        .where(TaskRow.company_id == company_id, or_(*(cast(TaskRow.id, String).like(f"%{r}") for r in refs)))
        .limit(2 * MAX_VISIBLE)
    )
    tasks = list(session.scalars(q))
    found: dict[str, str] = {}
    for ref in refs:
        matches = [t for t in tasks if t.id.hex.endswith(ref)]
        if len(matches) == 1:
            found[ref] = _task_label(matches[0])
    return found


def _threads(session: Session, company_id: UUID, keys: Sequence[str]) -> dict[str, str]:
    pairs = [decode_thread_key(k) for k in keys]
    ref = func.coalesce(MessageRow.thread_ref, MessageRow.provider_msg_id)
    rows = session.execute(
        select(MessageRow.channel, ref, func.count())
        .where(MessageRow.company_id == company_id, tuple_(MessageRow.channel, ref).in_(pairs), not_chat_only())
        .group_by(MessageRow.channel, ref)
        .limit(MAX_VISIBLE)
    ).all()
    return {
        encode_thread_key(channel, r): f"thread {encode_thread_key(channel, r)} | {channel.value} | {n} messages"
        for channel, r, n in rows
    }


def _norm(value: str) -> tuple[VisibleKind | None, str]:
    """The id's kind and its canonical form (the contract already normalises; kept so any caller is safe)."""
    kind = visible_kind(value)
    if kind is VisibleKind.uuid:
        return kind, str(UUID(value))
    if kind is VisibleKind.task_ref:
        return kind, value.lstrip("#").lower()
    return kind, value


def visible_labels(session: Session, company_id: UUID, ids: Sequence[str]) -> tuple[list[str], int]:
    """Labels in screen order for the ids that belong to the company, and how many ids got none."""
    wanted = [_norm(v) for v in ids[:MAX_VISIBLE]]
    uuids = [UUID(v) for k, v in wanted if k is VisibleKind.uuid]
    refs = [v for k, v in wanted if k is VisibleKind.task_ref]
    keys = [v for k, v in wanted if k is VisibleKind.thread_key]
    labels: dict[str, str] = {}
    if uuids:
        for lookup in (_cases, _approvals, _documents, _tasks_by_id):
            labels.update(lookup(session, company_id, uuids))
    if refs:
        labels.update(_tasks_by_ref(session, company_id, refs))
    if keys:
        labels.update(_threads(session, company_id, keys))
    found = [labels[v] for _, v in wanted if v in labels]
    return found, len(wanted) - len(found)

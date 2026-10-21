"""Server facts about the page the Super Agent was opened on (spec amendment 2026-10-16).

Every id in a validated `PageContext` is looked up company-scoped (invariant 4) with small bounded queries. A foreign,
unknown or stale id is dropped and only its KIND is reported in `dropped`, so facts never carry another company's
data, not even the id the client sent. The snapshot is not read here: it stays unverified client text.
`facts_text` renders plain text for the `<page_facts>` block; values are collapsed onto one line each so stored text
cannot fake a fact line, and `data_block` escapes every block tag.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import PageContext
from app.core.errors import NotFoundError
from app.db.models import ActionRow, Approval, AttachmentRow, CaseLink, DocumentRow, MessageRow, TaskRow
from app.pipeline import case_repo, owner_commands, work_repo
from app.pipeline.dashboard_decisions import is_suspicious
from app.pipeline.page_visible import visible_labels
from app.pipeline.read_repo import BadThreadKeyError, decode_thread_key

MAX_SUMMARY = 400
MAX_LINE = 160
MAX_DRAFT = 300
MAX_DRAFTS = 3
CASE_MESSAGES = 5
THREAD_MESSAGES = 8


def one_line(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


@dataclass(frozen=True)
class MessageFact:
    direction: str
    text: str  # first MAX_LINE characters, one line


@dataclass(frozen=True)
class CaseFact:
    case_id: UUID
    label: str
    state: str
    urgency: str
    summary: str
    messages: tuple[MessageFact, ...]


@dataclass(frozen=True)
class ThreadFact:
    thread_key: str
    channel: str
    case_id: UUID | None
    messages: tuple[MessageFact, ...]


@dataclass(frozen=True)
class ApprovalFact:
    approval_id: UUID
    case_id: UUID
    action_type: str
    status: str
    draft_version: int
    live: bool  # the approval is for the action's current draft
    suspicious: bool
    drafts: tuple[str, ...]


@dataclass(frozen=True)
class TaskFact:
    ref: str
    title: str
    due: str | None
    status: str


@dataclass(frozen=True)
class DocumentFact:
    attachment_id: UUID
    filename: str
    status: str


@dataclass(frozen=True)
class PageFacts:
    view: str
    case: CaseFact | None = None
    thread: ThreadFact | None = None
    approval: ApprovalFact | None = None
    task: TaskFact | None = None
    document: DocumentFact | None = None
    visible: tuple[str, ...] = ()
    dropped: tuple[str, ...] = field(default=())


def _messages(rows: Sequence[tuple[object, str]]) -> tuple[MessageFact, ...]:
    """Newest-first rows in, oldest-first facts out."""
    return tuple(MessageFact(str(getattr(d, "value", d)), one_line(t, MAX_LINE)) for d, t in reversed(rows))


def _case(session: Session, company_id: UUID, case_id: UUID) -> CaseFact | None:
    try:
        case = case_repo.get_case(session, company_id, case_id)
    except NotFoundError:
        return None
    rows = session.execute(
        select(MessageRow.direction, MessageRow.text)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(CaseLink.company_id == company_id, MessageRow.company_id == company_id, CaseLink.case_id == case.id)
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(CASE_MESSAGES)
    ).all()
    label = one_line(owner_commands.case_label(session, case), MAX_LINE)  # a display name may hold newlines
    messages = _messages([(d, t) for d, t in rows])
    return CaseFact(case.id, label, case.state.value, case.urgency.value, one_line(case.summary, MAX_SUMMARY), messages)


def _thread(session: Session, company_id: UUID, key: str) -> ThreadFact | None:
    try:
        channel, ref = decode_thread_key(key)
    except BadThreadKeyError:
        return None
    rows = session.execute(
        select(MessageRow.id, MessageRow.direction, MessageRow.text)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == channel,
            func.coalesce(MessageRow.thread_ref, MessageRow.provider_msg_id) == ref,
        )
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(THREAD_MESSAGES)
    ).all()
    if not rows:
        return None
    case_id = session.scalar(
        select(CaseLink.case_id)
        .where(CaseLink.company_id == company_id, CaseLink.message_id.in_([r[0] for r in rows]))
        .order_by(CaseLink.created_at.desc())
        .limit(1)
    )
    return ThreadFact(key, channel.value, case_id, _messages([(d, t) for _, d, t in rows]))


def _approval(session: Session, company_id: UUID, approval_id: UUID) -> ApprovalFact | None:
    row = session.execute(
        select(Approval, ActionRow)
        .join(ActionRow, ActionRow.id == Approval.action_id)
        .where(Approval.id == approval_id, Approval.company_id == company_id, ActionRow.company_id == company_id)
    ).first()
    if row is None:
        return None
    approval, action = row[0], row[1]
    variants = action.payload.get("body_variants") or ()
    drafts = tuple(one_line(str(v), MAX_DRAFT) for v in list(variants)[:MAX_DRAFTS])
    live = approval.draft_version == action.draft_version
    suspicious = is_suspicious(session, company_id, action)  # the decide gate's shared predicate
    return ApprovalFact(
        approval.id, action.case_id, action.type.value, approval.status.value, approval.draft_version, live,
        suspicious, drafts,
    )  # fmt: skip


def _task(session: Session, company_id: UUID, ref: str) -> TaskFact | None:
    try:
        task_id = work_repo.resolve_task(session, company_id, ref)
    except NotFoundError:
        return None
    task = session.scalar(select(TaskRow).where(TaskRow.company_id == company_id, TaskRow.id == task_id))
    if task is None:
        return None
    due = task.due_at.isoformat() if task.due_at else None
    return TaskFact(work_repo.short_ref(task.id), one_line(task.title, MAX_LINE), due, task.status.value)


def _document(session: Session, company_id: UUID, attachment_id: UUID) -> DocumentFact | None:
    row = session.execute(
        select(AttachmentRow.id, AttachmentRow.filename, DocumentRow.status)
        .outerjoin(
            DocumentRow, (DocumentRow.attachment_id == AttachmentRow.id) & (DocumentRow.company_id == company_id)
        )
        .where(AttachmentRow.company_id == company_id, AttachmentRow.id == attachment_id)
    ).first()
    if row is None:
        return None
    status = row[2].value if row[2] is not None else "not classified"
    return DocumentFact(row[0], one_line(row[1] or "unnamed", MAX_LINE), status)


def resolve_page_facts(session: Session, company_id: UUID, page: PageContext) -> PageFacts:
    """Authoritative facts for each present id; anything that does not resolve in this company is dropped."""
    case = _case(session, company_id, page.case_id) if page.case_id else None
    thread = _thread(session, company_id, page.thread_key) if page.thread_key else None
    approval = _approval(session, company_id, page.approval_id) if page.approval_id else None
    task = _task(session, company_id, page.task_ref) if page.task_ref else None
    document = _document(session, company_id, page.attachment_id) if page.attachment_id else None
    labels, missing = visible_labels(session, company_id, page.visible_ids)
    asked = (
        ("case", page.case_id, case),
        ("thread", page.thread_key, thread),
        ("approval", page.approval_id, approval),
        ("task", page.task_ref, task),
        ("document", page.attachment_id, document),
        ("visible", missing or None, None),
    )
    dropped = tuple(kind for kind, ident, fact in asked if ident is not None and fact is None)
    return PageFacts(page.view.value, case, thread, approval, task, document, tuple(labels), dropped)


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _message_lines(messages: tuple[MessageFact, ...]) -> list[str]:
    return [f"  message {m.direction}: {m.text}" for m in messages]


def _entity_lines(facts: PageFacts) -> list[str]:
    lines: list[str] = []
    if c := facts.case:
        lines += [f"open case: {c.case_id} | {c.label} | {c.state} | urgency {c.urgency}", f"  summary: {c.summary}"]
        lines += _message_lines(c.messages)
    if t := facts.thread:
        lines.append(f"open thread: {t.thread_key} | {t.channel} | case {t.case_id or 'none'}")
        lines += _message_lines(t.messages)
    if a := facts.approval:
        lines.append(
            f"open approval: {a.approval_id} | {a.action_type} | {a.status} | draft_version {a.draft_version} | "
            f"current draft {_yes(a.live)} | suspicious sender {_yes(a.suspicious)} | case {a.case_id}"
        )
        lines += [f"  draft {i}: {d}" for i, d in enumerate(a.drafts, 1)]
    if k := facts.task:
        lines.append(f"open task: #{k.ref} | {k.title} | due {k.due or 'none'} | {k.status}")
    if d := facts.document:
        lines.append(f"open document: {d.attachment_id} | {d.filename} | {d.status}")
    return lines


def facts_text(facts: PageFacts) -> str:
    """Plain text for the `<page_facts>` block (escaped there). Entities first, so truncation cuts visible rows."""
    lines = [f"view: {facts.view}", *_entity_lines(facts)]
    if facts.visible:
        lines += ["visible rows (screen order):", *(f"- {label}" for label in facts.visible)]
    if facts.dropped:
        lines.append(f"no longer exists (not shown): {', '.join(facts.dropped)}")
    if len(lines) == 1:
        lines.append("no page item")
    return "\n".join(lines)

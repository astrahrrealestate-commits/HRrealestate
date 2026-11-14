"""Server facts about the page the Super Agent was opened on (spec amendment 2026-10-16).

Every id in a validated `PageContext` is looked up company-scoped (invariant 4) with small bounded queries. A foreign,
unknown or stale id is dropped and only its KIND is reported in `dropped`, so facts never carry another company's
data, not even the id the client sent. The snapshot is not read here: it stays unverified client text.
`facts_text` renders plain text for the `<page_facts>` block; values are collapsed onto one line each so stored text
cannot fake a fact line, and `data_block` escapes every block tag.
An open thread or case also carries the memory pack (amendment 2026-10-22, `page_memory`): the conversation (the
thread's own messages when a thread is open, else the case's linked messages) and the case memory (the open case, or
the open thread's case). The whole text stays within `page_text.FACTS_BUDGET` (drop order in `page_text`).
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import PageContext
from app.core.errors import NotFoundError
from app.db.models import ActionRow, Approval, AttachmentRow, CaseLink, DocumentRow, TaskRow
from app.pipeline import case_repo, owner_commands, page_memory, work_repo
from app.pipeline.dashboard_decisions import is_suspicious
from app.pipeline.page_memory import CaseMemory, Conversation
from app.pipeline.page_memory_lines import conversation_lines, memory_lines
from app.pipeline.page_text import VISIBLE, Line, render
from app.pipeline.page_text import one_line as one_line
from app.pipeline.page_visible import visible_labels
from app.pipeline.read_repo import BadThreadKeyError, decode_thread_key

MAX_SUMMARY = 800
MAX_LINE = 160
MAX_DRAFT = 300
MAX_DRAFTS = 3


@dataclass(frozen=True)
class CaseFact:
    case_id: UUID
    label: str
    state: str
    urgency: str
    summary: str


@dataclass(frozen=True)
class ThreadFact:
    thread_key: str
    channel: str
    case_id: UUID | None


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
    thread_case: CaseFact | None = None  # the open thread's case when no case is open
    conversation: Conversation | None = None
    memory: CaseMemory | None = None  # of the open case, else of the open thread's case


def _case(session: Session, company_id: UUID, case_id: UUID) -> CaseFact | None:
    try:
        case = case_repo.get_case(session, company_id, case_id)
    except NotFoundError:
        return None
    label = one_line(owner_commands.case_label(session, case), MAX_LINE)  # a display name may hold newlines
    return CaseFact(case.id, label, case.state.value, case.urgency.value, one_line(case.summary, MAX_SUMMARY))


def _thread(session: Session, company_id: UUID, key: str) -> tuple[ThreadFact | None, Conversation | None]:
    try:
        channel, ref = decode_thread_key(key)
    except BadThreadKeyError:
        return None, None
    conversation, ids = page_memory.thread_conversation(session, company_id, channel, ref)
    if conversation is None:
        return None, None
    case_id = session.scalar(
        select(CaseLink.case_id)
        .where(CaseLink.company_id == company_id, CaseLink.message_id.in_(ids))
        .order_by(CaseLink.created_at.desc())
        .limit(1)
    )
    return ThreadFact(key, channel.value, case_id), conversation


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


def _memory(
    session: Session,
    company_id: UUID,
    case: CaseFact | None,
    thread: ThreadFact | None,
    thread_text: Conversation | None,
) -> tuple[CaseFact | None, Conversation | None, CaseMemory | None]:
    """(the thread's case header, the conversation, the case memory). A thread page reads only that thread's text."""
    conversation = thread_text
    if conversation is None and case is not None:
        conversation = page_memory.case_conversation(session, company_id, case.case_id)
    thread_case = None
    if case is None and thread is not None and thread.case_id is not None:
        thread_case = _case(session, company_id, thread.case_id)
    target = case or thread_case
    memory = page_memory.case_memory(session, company_id, target.case_id) if target else None
    return thread_case, conversation, memory


def resolve_page_facts(session: Session, company_id: UUID, page: PageContext) -> PageFacts:
    """Authoritative facts for each present id; anything that does not resolve in this company is dropped."""
    case = _case(session, company_id, page.case_id) if page.case_id else None
    thread, thread_text = _thread(session, company_id, page.thread_key) if page.thread_key else (None, None)
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
    thread_case, conversation, memory = _memory(session, company_id, case, thread, thread_text)
    return PageFacts(
        page.view.value, case, thread, approval, task, document, tuple(labels), dropped, thread_case, conversation,
        memory,
    )  # fmt: skip


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _memory_of(facts: PageFacts, case_id: UUID) -> list[Line]:
    return memory_lines(facts.memory) if facts.memory and facts.memory.case_id == case_id else []


def _case_lines(facts: PageFacts) -> list[Line]:
    lines: list[Line] = []
    if c := facts.case:
        lines += [Line(f"open case: {c.case_id} | {c.label} | {c.state} | urgency {c.urgency}")]
        lines += [Line(f"  summary: {c.summary}"), *_memory_of(facts, c.case_id)]
    if t := facts.thread:
        lines.append(Line(f"open thread: {t.thread_key} | {t.channel} | case {t.case_id or 'none'}"))
        if (tc := facts.thread_case) and tc.case_id == t.case_id:
            lines += [Line(f"  case: {tc.label} | {tc.state} | urgency {tc.urgency}"), Line(f"  summary: {tc.summary}")]
            lines += _memory_of(facts, tc.case_id)
    return lines


def _entity_lines(facts: PageFacts) -> list[Line]:
    lines = _case_lines(facts)
    if a := facts.approval:
        lines.append(
            Line(
                f"open approval: {a.approval_id} | {a.action_type} | {a.status} | draft_version {a.draft_version} | "
                f"current draft {_yes(a.live)} | suspicious sender {_yes(a.suspicious)} | case {a.case_id}"
            )
        )
        lines += [Line(f"  draft {i}: {d}") for i, d in enumerate(a.drafts, 1)]
    if k := facts.task:
        lines.append(Line(f"open task: #{k.ref} | {k.title} | due {k.due or 'none'} | {k.status}"))
    if d := facts.document:
        lines.append(Line(f"open document: {d.attachment_id} | {d.filename} | {d.status}"))
    return lines


def facts_text(facts: PageFacts) -> str:
    """Plain text for the `<page_facts>` block (escaped there): entities with the case memory, the conversation,
    visible rows, then what no longer exists; within `FACTS_BUDGET` (`page_text.render` drop order)."""
    lines = [Line(f"view: {facts.view}"), *_entity_lines(facts)]
    if facts.conversation:
        lines += conversation_lines(facts.conversation)
    if facts.visible:
        rows = [Line(f"- {label}", VISIBLE, -i) for i, label in enumerate(facts.visible)]
        lines += [Line("visible rows (screen order):"), *rows]
    if facts.dropped:
        lines.append(Line(f"no longer exists (not shown): {', '.join(facts.dropped)}"))
    if len(lines) == 1:
        lines.append(Line("no page item"))
    return render(lines)

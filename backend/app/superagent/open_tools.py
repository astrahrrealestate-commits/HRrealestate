"""Open one mail, thread, document or person in full for the research loop. Read only, every query company-scoped; None
means "not available" (another company's id, a chat kept only in Chats, a flagged document) and never says which.
Texts are untrusted: the caller puts them in a data block."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.budget import clip
from app.contracts.person_memory import PersonMemory
from app.core.ids import case_ref
from app.db.enums import ExtractionStatus
from app.db.models import (
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    DocumentChunk,
    DocumentRow,
    Lease,
    LeaseParty,
    MessageRow,
    Person,
    Unit,
)
from app.db.models.finance import QuoteReview, QuoteRow
from app.db.models.ingestion import not_chat_only
from app.pipeline.concierge_entities import resolve_entities
from app.pipeline.concierge_sanitize import plain_line, redact_contact
from app.pipeline.conversation import People, line_of, load_people, new_part, quoted_lines
from app.pipeline.document_search import DocFilter, doc_filters
from app.pipeline.injection_scan import scan
from app.pipeline.person_memory import stored_memory

MAIL_CHARS = 8_000
ATTACHMENT_CHARS = 6_000
THREAD_MAIL_CHARS = 1_500
THREAD_CHARS = 14_000
MAX_THREAD = 60
PAGE_CHARS = 6_000
MAX_CASES = 10


def _message(session: Session, company_id: UUID, message_id: UUID) -> MessageRow | None:
    return session.scalar(
        select(MessageRow).where(MessageRow.company_id == company_id, MessageRow.id == message_id, not_chat_only())
    )


def _attachments(session: Session, company_id: UUID, message_id: UUID) -> list[str]:
    rows: Sequence[AttachmentRow] = session.scalars(
        select(AttachmentRow)
        .where(AttachmentRow.company_id == company_id, AttachmentRow.message_id == message_id)
        .order_by(AttachmentRow.id)
    ).all()
    flagged = set(
        session.scalars(
            select(DocumentRow.attachment_id).where(
                DocumentRow.company_id == company_id,
                DocumentRow.attachment_id.in_([a.id for a in rows]),
                DocumentRow.suspicious.is_(True),
            )
        )
    )
    return [_attachment_text(a, a.id in flagged) for a in rows]


def _attachment_text(att: AttachmentRow, flagged: bool) -> str:
    name = f"attachment {att.filename or 'unnamed'}"
    if att.extraction_status is not ExtractionStatus.done or not att.extracted_text:
        return f"{name} (not read)"
    if flagged or scan(att.extracted_text) is not None:
        return f"{name} (withheld: it tries to give instructions)"
    return f"{name}:\n{clip(att.extracted_text, ATTACHMENT_CHARS)}"


def _render(row: MessageRow, people: People, limit: int, text: str | None = None) -> str:
    """The dossier's line rules: the author is the directory name or the address (never a header display name),
    Harjot's own mail is "Harjot (sent)" and a copy of it "not verified", the message's own line breaks continue as
    `    | `, and a body that looks like instructions is marked. Nothing in a mail can write a line of its own."""
    line = line_of(row, people, text=clip(text if text is not None else new_part(row), limit))
    subject = (row.meta or {}).get("subject")
    head = f"subject: {' '.join(str(subject).split())[:200]}\n" if subject else ""
    return head + line.render()


def open_message(session: Session, company_id: UUID, message_id: UUID) -> str | None:
    msg = _message(session, company_id, message_id)
    if msg is None:
        return None
    people = load_people(session, company_id, [msg])
    parts = [_render(msg, people, MAIL_CHARS, text=msg.text), *_attachments(session, company_id, message_id)]
    return "\n\n".join(parts)


def _thread_rows(session: Session, company_id: UUID, msg: MessageRow) -> Sequence[MessageRow]:
    same = MessageRow.thread_ref == msg.thread_ref if msg.thread_ref else MessageRow.id == msg.id
    return session.scalars(
        select(MessageRow)
        .where(MessageRow.company_id == company_id, MessageRow.channel == msg.channel, same, not_chat_only())
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(MAX_THREAD + 1)
    ).all()


def open_thread(session: Session, company_id: UUID, message_id: UUID) -> str | None:
    """Both directions, oldest first, each message's new part; Harjot's replies that exist only as quotes are added,
    marked not verified. When it does not fit, the oldest messages are the ones left out."""
    msg = _message(session, company_id, message_id)
    if msg is None:
        return None
    newest = _thread_rows(session, company_id, msg)
    rows = list(newest[:MAX_THREAD])
    people = load_people(session, company_id, rows)
    texts = [_render(row, people, THREAD_MAIL_CHARS) for row in rows]
    quoted = quoted_lines(rows, people, frozenset(), [new_part(r) for r in rows])
    texts += [q.render() for q in quoted]
    kept: list[str] = []
    used = 0
    for text in texts:
        if kept and used + len(text) > THREAD_CHARS:
            break
        kept.append(text)
        used += len(text)
    if len(kept) < len(texts) or len(newest) > MAX_THREAD:
        kept.append("(earlier messages not shown)")
    return "\n\n".join(reversed(kept))


def open_document(session: Session, company_id: UUID, document_id: UUID, page: int = 1) -> str | None:
    doc = session.scalar(
        select(DocumentRow).where(
            *doc_filters(company_id, DocFilter(readable_only=True)), DocumentRow.id == document_id
        )
    )
    if doc is None:
        return None
    chunks = session.scalars(
        select(DocumentChunk.text)
        .where(DocumentChunk.company_id == company_id, DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.ord)
    )
    text = "\n".join(chunks)
    pages = max(1, -(-len(text) // PAGE_CHARS))
    if not 1 <= page <= pages:
        return None
    body = text[(page - 1) * PAGE_CHARS : page * PAGE_CHARS]
    return f"{doc.title} ({doc.doc_type}, {doc.document_date or 'undated'}), page {page} of {pages}\n\n{body}"


def _memory_lines(memory: PersonMemory | None) -> list[str]:
    """What EstateOS remembers about the person (written from their own mail, so untrusted like it)."""
    if memory is None:
        return []
    lines = [f"memory: {memory.summary}"]
    lines += [f"promised: {c}" for c in memory.commitments]
    lines += [f"prefers: {p}" for p in memory.preferences]
    lines += [f"open: {o}" for o in memory.open_issues]
    return lines


def open_person(session: Session, company_id: UUID, person_id: UUID) -> str | None:
    person = session.scalar(select(Person).where(Person.company_id == company_id, Person.id == person_id))
    if person is None:
        return None
    lines = [f"{person.display_name} | {person.kind.value}" + (f" | {person.trade}" if person.trade else "")]
    lines += _memory_lines(stored_memory(session, company_id, person_id))
    leases = session.execute(
        select(Unit.label, Lease.valid_from, Lease.valid_to)
        .join(Lease, Lease.unit_id == Unit.id)
        .join(LeaseParty, LeaseParty.lease_id == Lease.id)
        .where(LeaseParty.company_id == company_id, Unit.company_id == company_id, LeaseParty.person_id == person_id)
        .order_by(Lease.valid_from.desc())
    )
    lines += [f"lease: {label} | {start} to {end or 'now'}" for label, start, end in leases]
    cases = session.scalars(
        select(Case)
        .where(Case.company_id == company_id, Case.primary_person_id == person_id)
        .order_by(Case.opened_at.desc(), Case.id.desc())
        .limit(MAX_CASES)
    )
    lines += [f"case: {c.state.value} | {c.category.value} | {c.urgency.value} | {clip(c.summary, 400)}" for c in cases]
    return "\n".join(lines)


def named_people(engine: Engine, company_id: UUID, question: str) -> tuple[tuple[UUID, str], ...]:
    """The people a question names (id and display name), best match first."""
    with Session(engine) as session:
        return tuple((p.id, p.label) for p in resolve_entities(session, company_id, question).people)


def open_case(session: Session, company_id: UUID, case_id: UUID) -> str | None:
    """Open one case's full operational summary, contact, unit, pending actions/approvals, and quote reviews."""
    case = session.scalar(select(Case).where(Case.company_id == company_id, Case.id == case_id))
    if case is None:
        return None
    person = (
        session.scalar(select(Person).where(Person.company_id == company_id, Person.id == case.primary_person_id))
        if case.primary_person_id
        else None
    )
    unit = (
        session.scalar(select(Unit).where(Unit.company_id == company_id, Unit.id == case.unit_id))
        if case.unit_id
        else None
    )
    who = f"{person.display_name} ({person.trade or person.kind.value})" if person else "Unknown contact"
    where = (unit.address or unit.label) if unit else "General"
    brixx = f" | BRIXX #{case.brixx_ref}" if case.brixx_ref else ""
    lines = [
        f"Case #{case_ref(case.id)} | {case.category.value} | {case.state.value} | {case.urgency.value}{brixx}",
        f"Contact: {redact_contact(plain_line(who))} | Property: {plain_line(where)}",
        f"Opened: {case.opened_at.strftime('%Y-%m-%d %H:%M') if case.opened_at else 'unknown'}",
        f"Summary: {redact_contact(clip(case.summary or 'No summary yet.', 1500))}",
    ]
    actions = session.scalars(
        select(ActionRow)
        .where(ActionRow.company_id == company_id, ActionRow.case_id == case.id)
        .order_by(ActionRow.created_at.desc())
        .limit(5)
    ).all()
    if actions:
        apprs = {
            a.action_id: a.status.value
            for a in session.scalars(
                select(Approval).where(
                    Approval.company_id == company_id, Approval.action_id.in_([act.id for act in actions])
                )
            ).all()
        }
        for act in actions:
            appr_st = apprs.get(act.id, "-")
            lines.append(
                f"Action: {act.type.value} | status={act.status.value} | approval={appr_st} | v{act.draft_version}"
            )
    reviews = session.execute(
        select(QuoteRow.total, QuoteRow.currency, QuoteReview.verdict, QuoteReview.overcharge)
        .join(QuoteReview, QuoteReview.quote_id == QuoteRow.id)
        .where(QuoteRow.company_id == company_id, QuoteRow.case_id == case.id)
        .order_by(QuoteRow.created_at.desc())
        .limit(3)
    ).all()
    for total, currency, verdict, overcharge in reviews:
        over = f", overcharge={overcharge}" if overcharge else ""
        lines.append(f"Quote review: {currency} {total} | verdict={verdict.value}{over}")
    return "\n".join(lines)

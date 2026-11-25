"""Open one mail, thread, document or person in full for the research loop. Read only, every query company-scoped; None
means "not available" (another company's id, a chat kept only in Chats, a flagged document) and never says which.
Texts are untrusted: the caller puts them in a data block."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.budget import clip
from app.context.shown_sender import shown_sender_name
from app.contracts import Direction
from app.core.localtime import to_local
from app.db.enums import ExtractionStatus
from app.db.models import AttachmentRow, Case, DocumentChunk, DocumentRow, Lease, LeaseParty, MessageRow, Person, Unit
from app.db.models.ingestion import not_chat_only
from app.pipeline.concierge_entities import resolve_entities
from app.pipeline.document_search import DocFilter, doc_filters
from app.pipeline.injection_scan import scan

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


def _sender(session: Session, msg: MessageRow) -> str:
    if msg.direction is Direction.outbound:
        return "Harjot"
    name = session.scalar(
        select(Person.display_name).where(Person.company_id == msg.company_id, Person.id == msg.person_id)
    )
    return shown_sender_name(msg, name)


def _head(session: Session, msg: MessageRow) -> str:
    subject = (msg.meta or {}).get("subject")
    head = f"{to_local(msg.sent_at):%Y-%m-%d %H:%M} | {msg.channel.value} | {_sender(session, msg)}"
    return f"{head} | {subject}" if subject else head


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


def open_message(session: Session, company_id: UUID, message_id: UUID) -> str | None:
    msg = _message(session, company_id, message_id)
    if msg is None:
        return None
    parts = [_head(session, msg), clip(msg.text, MAIL_CHARS), *_attachments(session, company_id, message_id)]
    return "\n\n".join(parts)


def open_thread(session: Session, company_id: UUID, message_id: UUID) -> str | None:
    """Both directions, oldest first; when it does not fit, the oldest messages are the ones left out."""
    msg = _message(session, company_id, message_id)
    if msg is None:
        return None
    same = MessageRow.thread_ref == msg.thread_ref if msg.thread_ref else MessageRow.id == msg.id
    newest = session.scalars(
        select(MessageRow)
        .where(MessageRow.company_id == company_id, MessageRow.channel == msg.channel, same, not_chat_only())
        .order_by(MessageRow.sent_at.desc(), MessageRow.id.desc())
        .limit(MAX_THREAD + 1)
    ).all()
    kept: list[str] = []
    used = 0
    for row in newest[:MAX_THREAD]:
        text = f"{_head(session, row)}\n{clip(row.text, THREAD_MAIL_CHARS)}"
        if kept and used + len(text) > THREAD_CHARS:
            break
        kept.append(text)
        used += len(text)
    if len(kept) < len(newest):
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


def open_person(session: Session, company_id: UUID, person_id: UUID) -> str | None:
    person = session.scalar(select(Person).where(Person.company_id == company_id, Person.id == person_id))
    if person is None:
        return None
    lines = [f"{person.display_name} | {person.kind.value}" + (f" | {person.trade}" if person.trade else "")]
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

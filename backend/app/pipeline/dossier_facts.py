"""Owner rules, open waits and unread attachments for a dossier (M13)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.memory_items import get_active_preferences
from app.db.enums import ExtractionStatus, WaitStatus
from app.db.models import AttachmentRow, MessageRow, WaitRow
from app.pipeline.document_policy import FileMeta, looks_like_id, should_skip

MAX_RULES = 20


def open_waits(session: Session, company_id: UUID, case_id: UUID | None) -> tuple[str, ...]:
    if case_id is None:
        return ()
    rows = session.scalars(
        select(WaitRow.about).where(
            WaitRow.company_id == company_id, WaitRow.case_id == case_id, WaitRow.status == WaitStatus.waiting
        )
    )
    return tuple(rows)


def owner_rules(session: Session, company_id: UUID, scope_ids: Sequence[UUID | None]) -> tuple[str, ...]:
    """Harjot's active standing rules for the company and for this person, case or unit."""
    ids = [i for i in scope_ids if i is not None]
    items = get_active_preferences(session, company_id, scope_ids=ids, limit=MAX_RULES)
    return tuple(" ".join(item.text.split()) for item in items)


def unread_attachments(session: Session, msg: MessageRow, message_ids: Sequence[UUID] = ()) -> tuple[str, ...]:
    """File names of readable attachments on this message or its thread that lack text (failed/budgeted read): the
    draft names them instead of asking for a file already sent. Identity documents and logos are left out."""
    mids = list(dict.fromkeys([msg.id, *message_ids]))
    rows = session.execute(
        select(AttachmentRow, MessageRow.sent_at)
        .join(MessageRow, MessageRow.id == AttachmentRow.message_id)
        .where(AttachmentRow.company_id == msg.company_id, AttachmentRow.message_id.in_(mids))
        .order_by((AttachmentRow.message_id == msg.id).desc(), MessageRow.sent_at.desc())
    ).all()
    return tuple(
        r.filename or "unnamed"
        for r, sent_at in rows
        if not (r.extraction_status is ExtractionStatus.done and (r.extracted_text or "").strip())
        and not should_skip(meta := FileMeta(r.filename, r.mime_type, r.size_bytes, sent_at))
        and not looks_like_id(meta)
    )

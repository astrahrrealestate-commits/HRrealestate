"""Read a message's attachments before its draft is written (M13): the proposer sees the quote, the lease clause or
the photo text in the first draft, not only after filing. Filing, linking and Drive stay after the draft.

Identity documents (by file name) and logos are never read (ADR 0007). Reading is idempotent: an attachment read
before (by an earlier run or by filing) is not read again. One unreadable file never stops the others or the draft.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import AttachmentRow, MessageRow
from app.pipeline.document_policy import FileMeta, looks_like_id, should_skip
from app.pipeline.document_reading import Unread, attachment_text
from app.pipeline.dossier import allowed_attachment_scope
from app.storage.extract import TextExtractor, canonical_mime
from app.storage.ports import ObjectStorage

log = get_logger(__name__)


def readable(row: AttachmentRow, sent_at: datetime) -> bool:
    meta = FileMeta(row.filename, row.mime_type, row.size_bytes, sent_at)
    return not should_skip(meta) and not looks_like_id(meta)


def read_attachments(
    engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor, message_id: UUID
) -> int:
    """How many attachments now have text across the mail and its allowed thread. Budget stops retry later."""
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        if msg is None:
            return 0
        mids, photos_only = allowed_attachment_scope(session, msg)
        rows = session.execute(
            select(AttachmentRow, MessageRow.sent_at)
            .join(MessageRow, MessageRow.id == AttachmentRow.message_id)
            .where(AttachmentRow.company_id == msg.company_id, AttachmentRow.message_id.in_(mids))
            .order_by((AttachmentRow.message_id == msg.id).desc(), MessageRow.sent_at.desc())
        ).all()
        wanted = [
            (r.id, msg.company_id)
            for r, sent_at in rows
            if readable(r, sent_at)
            and (r.message_id not in photos_only or canonical_mime(r.mime_type, r.filename).startswith("image/"))
        ]
    done = 0
    for attachment_id, company_id in wanted:
        try:
            text = attachment_text(engine, settings, storage, extractor, company_id, attachment_id)
        except Exception as exc:  # a missing object or a broken file: the draft goes ahead without it
            log.warning("draft_reading.unreadable", attachment_id=str(attachment_id), error_type=type(exc).__name__)
            continue
        done += not isinstance(text, Unread)
    return done

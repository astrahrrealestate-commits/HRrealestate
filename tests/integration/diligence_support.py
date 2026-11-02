"""Builders for due diligence integration tests: a library document with extracted text."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.db.enums import ExtractionStatus
from app.db.models import AttachmentRow, DocumentRow, MessageRow, RawEvent

SENT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def make_document(
    session: Session,
    company_id: UUID,
    text: str | None,
    *,
    filename: str = "doc.pdf",
    doc_type: str = "other",
    suspicious: bool = False,
) -> UUID:
    """Adds a message, attachment (with `text` as its extracted text) and document row; returns the document id."""
    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
    session.add(raw)
    session.flush()
    msg = MessageRow(
        company_id=company_id, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
        thread_ref="t", sender_identity="agent@example.test", direction=Direction.inbound, sent_at=SENT,
        text="bijlage", meta={},
    )  # fmt: skip
    session.add(msg)
    session.flush()
    att = AttachmentRow(
        company_id=company_id, message_id=msg.id, s3_key=f"k/{new_id()}", mime_type="application/pdf",
        filename=filename, size_bytes=9, sha256="0" * 64, extracted_text=text,
        extraction_status=ExtractionStatus.done if text else None,
    )  # fmt: skip
    session.add(att)
    session.flush()
    doc = DocumentRow(
        company_id=company_id, attachment_id=att.id, doc_type=doc_type, title=filename, file_name=filename,
        confidence=0.9, suspicious=suspicious,
    )  # fmt: skip
    session.add(doc)
    session.flush()
    return doc.id

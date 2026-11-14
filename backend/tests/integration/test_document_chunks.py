"""M10 document_chunks: the generated `tsv` matches Dutch stems and exact tokens; rows are unique per (doc, ord)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.db.models import AttachmentRow, Company, DocumentChunk, DocumentRow, MessageRow, RawEvent

pytestmark = pytest.mark.integration


def _document(db: Session, company: Company) -> DocumentRow:
    raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
    db.add(raw)
    db.flush()
    msg = MessageRow(company_id=company.id, raw_event_id=raw.id, channel=Channel.gmail,
                     provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="x@example.test",
                     direction=Direction.inbound, sent_at=datetime(2026, 10, 6, tzinfo=UTC),
                     text="t", meta={})  # fmt: skip
    db.add(msg)
    db.flush()
    att = AttachmentRow(company_id=company.id, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                        filename="huur.pdf", size_bytes=10, sha256="0" * 64)  # fmt: skip
    db.add(att)
    db.flush()
    doc = DocumentRow(company_id=company.id, attachment_id=att.id, doc_type="lease", title="Huurovereenkomst",
                      file_name="x.pdf", confidence=0.9)  # fmt: skip
    db.add(doc)
    db.flush()
    return doc


def _hits(db: Session, company: Company, query: str) -> int:
    tsq = func.websearch_to_tsquery("dutch", query).op("||")(func.websearch_to_tsquery("simple", query))
    stmt = select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.company_id == company.id, DocumentChunk.tsv.op("@@")(tsq)
    )  # fmt: skip
    return int(db.scalar(stmt) or 0)


def test_tsv_matches_dutch_stem_and_exact_token(db: Session, company: Company) -> None:
    doc = _document(db, company)
    text = "De huurder betaalt een waarborgsom van twee maanden. Opzegtermijn: drie maanden."
    db.add(DocumentChunk(company_id=company.id, document_id=doc.id, ord=0, text=text))
    db.flush()
    assert _hits(db, company, "waarborgsom") == 1
    assert _hits(db, company, "huurders") == 1  # Dutch stemming: huurders -> huurder
    assert _hits(db, company, "deposit") == 0


def test_chunk_unique_per_document_and_order(db: Session, company: Company) -> None:
    doc = _document(db, company)
    db.add(DocumentChunk(company_id=company.id, document_id=doc.id, ord=0, text="een"))
    db.flush()
    db.add(DocumentChunk(company_id=company.id, document_id=doc.id, ord=0, text="twee"))
    with pytest.raises(IntegrityError):
        db.flush()

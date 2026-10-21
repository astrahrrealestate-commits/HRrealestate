"""#9 Document reading (M10, ADR 0007): get an attachment's text, then let the doc_reader agent understand it.

Text is extracted once per attachment and stored on `attachments` (`extraction_status` is the marker, so a retry or a
second caller reuses it). Scans and photos go through the doc_ocr vision agent. Every failure here is a fallback, not an
error: the caller then files from metadata alone (the M9 path). Transient provider errors still propagate for the DBOS
step to retry. ID documents never get here (the caller checks), and if the reader finds one anyway the text is purged.
"""

from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.messages import BinaryContent, UserContent
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.contracts import DocType, DocumentFacts
from app.core.errors import AgentFailedError, BudgetExceededError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import ExtractionStatus
from app.db.models import AttachmentRow
from app.llm.agents.doc_reader import DOC_OCR, DOC_READER, doc_reader_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline.injection_scan import scan
from app.storage.extract import Extraction, TextExtractor
from app.storage.ports import ObjectStorage

log = get_logger(__name__)
READER_VERSION = DOC_READER.prompt.version
_VISION_TYPES = ("image/jpeg", "image/png", "image/webp", "application/pdf")
_OCR_INSTRUCTION = "Transcribe the text in this document."


@dataclass(frozen=True)
class Reading:
    facts: DocumentFacts
    call_id: UUID
    text: str
    suspicious: bool


@dataclass(frozen=True)
class ReadInput:
    company_id: UUID
    attachment_id: UUID
    filename: str | None
    mime_type: str
    size_bytes: int
    sender: str
    message_text: str
    case_summary: str | None


def _ocr(engine: Engine, settings: Settings, data: bytes, mime_type: str, company_id: UUID) -> str:
    content: list[UserContent] = [_OCR_INSTRUCTION, BinaryContent(data=data, media_type=mime_type)]
    return run_agent(engine, settings, DOC_OCR, content, CallContext(company_id, "doc_ocr")).output.text.strip()


def _save(engine: Engine, company_id: UUID, attachment_id: UUID, ex: Extraction, text: str | None) -> None:
    status = (
        ExtractionStatus.done
        if text
        else (ex.status if ex.status is not ExtractionStatus.done else ExtractionStatus.skipped)
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(AttachmentRow)
            .where(AttachmentRow.id == attachment_id, AttachmentRow.company_id == company_id)
            .values(extracted_text=text, extraction_status=status, page_count=ex.page_count, extractor=ex.extractor)
        )


def _extract(engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor,
             row: AttachmentRow) -> str | None:  # fmt: skip
    """Run the extractor (and vision for scans) and store the outcome. None = no text; budget stops are not stored."""
    ex = extractor.extract(storage.get(row.s3_key), row.mime_type, row.filename)
    text = ex.text
    if text is None and ex.needs_ocr and row.mime_type in _VISION_TYPES:
        try:
            text = _ocr(engine, settings, storage.get(row.s3_key), row.mime_type, row.company_id) or None
        except BudgetExceededError:
            return None  # not stored: a later run, with budget, reads it
        except AgentFailedError:
            ex = Extraction(ExtractionStatus.failed, None, ex.page_count, "doc_ocr", note="vision failed")
    _save(engine, row.company_id, row.id, ex, text)
    return text


def attachment_text(engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor,
                    company_id: UUID, attachment_id: UUID) -> str | None:  # fmt: skip
    with Session(engine, expire_on_commit=False) as session:
        row = session.get(AttachmentRow, attachment_id)
    if row is None or row.company_id != company_id:
        raise NotFoundError(f"attachment {attachment_id} not found for company {company_id}")
    if row.extraction_status is not None:
        return row.extracted_text if row.extraction_status is ExtractionStatus.done else None
    return _extract(engine, settings, storage, extractor, row)


def purge_text(engine: Engine, company_id: UUID, attachment_id: UUID) -> None:
    """The reader found an identity document: forget the text (ADR 0007)."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(AttachmentRow)
            .where(AttachmentRow.id == attachment_id, AttachmentRow.company_id == company_id)
            .values(extracted_text=None, extraction_status=ExtractionStatus.skipped)
        )


def read_document(engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor,
                  f: ReadInput) -> Reading | None:  # fmt: skip
    """Facts for one attachment, or None when it cannot be read (no text, budget spent, invalid answer)."""
    text = attachment_text(engine, settings, storage, extractor, f.company_id, f.attachment_id)
    if not text:
        return None
    prompt = doc_reader_prompt(f.filename, f.mime_type, f.size_bytes, f.sender, f.message_text, f.case_summary, text)
    try:
        result = run_agent(engine, settings, DOC_READER, prompt, CallContext(f.company_id, "doc_reader"))
    except (BudgetExceededError, AgentFailedError) as exc:
        log.warning("documents.reader_fallback", attachment_id=str(f.attachment_id), reason=type(exc).__name__)
        return None
    if result.output.doc_type is DocType.id_document:
        purge_text(engine, f.company_id, f.attachment_id)
        return Reading(result.output, result.model_call_id, "", False)
    return Reading(result.output, result.model_call_id, text, scan(text) is not None)


def facts_columns(reading: Reading) -> dict[str, object]:
    """The `documents` columns a reading fills. Identity documents keep no summary, facts or text."""
    f = reading.facts
    if f.doc_type is DocType.id_document:
        return {"reader_version": READER_VERSION}
    detail = f.model_dump(mode="json", include={"parties", "unit_hint", "start_date", "end_date", "key_facts"})
    return {
        "summary": f.summary, "facts": detail, "document_date": f.document_date,
        "reader_version": READER_VERSION, "suspicious": reading.suspicious,
    }  # fmt: skip

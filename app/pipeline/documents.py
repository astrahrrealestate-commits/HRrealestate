"""#9 Document Filing: classify one attachment, then file it in Drive, ask the owner, or skip it.

One `documents` row per attachment (unique `attachment_id`) carries the whole decision, Postgres before work:
- `filed` / `skipped` are final; `review` waits for the owner (`owner_doc_type`, or `skip_document`).
- Before any upload a `pending` row is claimed first-writer-wins with the classification, the target name and
  folder, and a Drive file id reserved up front. Retries and concurrent callers (a replayed step, a double tap)
  read that row instead of classifying again, and upload with the same id: Drive refuses a second file with it.
- Transient model and Drive errors propagate for the DBOS step to retry; an invalid model answer is `failed`.
Callers use deterministic workflow ids: `doc:{attachment_id}`, and `doc:{attachment_id}:owner:<choice>`.

The classifier sees metadata only: file name, type, size, sender, message text, case summary. Then, unless the file is
an identity document, the text is extracted and the doc_reader agent understands it (M10, ADR 0007,
`document_reading.py`); its facts and the searchable chunks are stored with the same row. Any reading failure falls back
to the metadata result, so a document is always filed or sent to review. Content with an injection pattern is always
sent to review.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Engine, Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import DocType, DocumentClassification
from app.core.errors import AgentFailedError, BudgetExceededError, EstateOSError, NotFoundError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import DocumentStatus
from app.db.models import AttachmentRow, Case, CaseLink, Company, DocumentRow, MessageRow, Person
from app.llm.agents.doc_classifier import DOC_CLASSIFIER, doc_classifier_prompt
from app.llm.calls import CallContext, run_agent
from app.pipeline.document_chunks import store_chunks
from app.pipeline.document_policy import (
    FileMeta,
    file_name,
    filing_status,
    folder_path,
    looks_like_id,
    name_date,
    should_skip,
)
from app.pipeline.document_reading import ReadInput, facts_columns, read_document
from app.storage.drive import DriveStore
from app.storage.extract import TextExtractor
from app.storage.ports import ObjectStorage

log = get_logger(__name__)
_FINAL = (DocumentStatus.filed, DocumentStatus.skipped)
_REOPENABLE = (DocumentStatus.review, DocumentStatus.failed)  # an upsert may replace these, nothing else


@dataclass(frozen=True)
class _Filing:
    company_id: UUID
    attachment_id: UUID
    s3_key: str
    meta: FileMeta
    party: str
    tz: str
    message_text: str
    case_summary: str | None
    existing: DocumentRow | None


@dataclass(frozen=True)
class _Decision:
    """What the model path decided for a document that can be filed: its classification and what reading added."""

    cls: DocumentClassification
    call_id: UUID | None
    extra: dict[str, object] = field(default_factory=dict)  # documents columns from the reader (summary, facts, ...)
    text: str | None = None  # extracted text to index; None for metadata-only decisions


def _row_query(company_id: UUID, attachment_id: UUID) -> Select[DocumentRow]:
    return select(DocumentRow).where(DocumentRow.attachment_id == attachment_id, DocumentRow.company_id == company_id)


def _load(engine: Engine, company_id: UUID, attachment_id: UUID) -> _Filing:
    query = (
        select(AttachmentRow, MessageRow, Person.display_name, Company.timezone, Case.summary)
        .join(MessageRow, (MessageRow.id == AttachmentRow.message_id) & (MessageRow.company_id == company_id))
        .join(Company, Company.id == AttachmentRow.company_id)
        .outerjoin(Person, (Person.id == MessageRow.person_id) & (Person.company_id == company_id))
        .outerjoin(CaseLink, (CaseLink.message_id == MessageRow.id) & (CaseLink.company_id == company_id))
        .outerjoin(Case, (Case.id == CaseLink.case_id) & (Case.company_id == company_id))
        .where(AttachmentRow.id == attachment_id, AttachmentRow.company_id == company_id)
    )
    with Session(engine, expire_on_commit=False) as session:
        found = session.execute(query).one_or_none()
        if found is None:
            raise NotFoundError(f"attachment {attachment_id} not found for company {company_id}")
        att, msg, display_name, tz, case_summary = found
        existing = session.scalar(_row_query(company_id, attachment_id))
    meta = FileMeta(filename=att.filename, mime_type=att.mime_type, size_bytes=att.size_bytes, sent_at=msg.sent_at)
    party = display_name or "unknown"  # never a raw phone number or email address in Harjot's Drive
    return _Filing(company_id, attachment_id, att.s3_key, meta, party, tz, msg.text, case_summary, existing)


def _upsert(engine: Engine, f: _Filing, values: dict[str, object], text: str | None = None) -> DocumentRow:
    """Insert, or replace a review/failed row (never a pending or final one); return the row that now stands.
    `text` is chunked into `document_chunks` in the same transaction (repeats are no-ops)."""
    stmt = insert(DocumentRow).values(company_id=f.company_id, attachment_id=f.attachment_id, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DocumentRow.attachment_id],
        set_=values,
        where=(DocumentRow.company_id == f.company_id) & DocumentRow.status.in_(_REOPENABLE),
    )
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.execute(stmt)
        row = session.scalar(_row_query(f.company_id, f.attachment_id))
        if row is not None and text:
            store_chunks(session, f.company_id, row.id, text)
    if row is None:  # the attachment id belongs to another company's row: unreachable after _load's scoping
        raise NotFoundError(f"document row for attachment {f.attachment_id} not in company {f.company_id}")
    return row


def _values(f: _Filing, status: DocumentStatus, cls: DocumentClassification, **extra: object) -> dict[str, object]:
    name = "" if status is DocumentStatus.skipped else file_name(cls, f.meta, f.party, f.tz)
    base: dict[str, object] = {"doc_type": cls.doc_type.value, "title": cls.title, "confidence": cls.confidence,
                               "status": status, "file_name": name, "error": None}  # fmt: skip
    return base | extra


def _claim(engine: Engine, f: _Filing, d: _Decision, reserved: str) -> DocumentRow:
    """First writer wins: the pending plan (name, folder, reserved Drive id) is in Postgres before any upload."""
    folder = "/".join(folder_path(d.cls, f.meta, f.tz))
    plan = _values(
        f,
        DocumentStatus.pending,
        d.cls,
        drive_folder=folder,
        drive_file_id=reserved,
        model_call_id=d.call_id,
        **d.extra,
    )
    return _upsert(engine, f, plan, d.text)


def _owner_choice(f: _Filing, doc_type: DocType) -> tuple[DocumentClassification, UUID | None]:
    """The owner picked the type: keep the model's title and document date, confidence 1."""
    title = ((f.existing.title if f.existing else None) or f.meta.filename or "Document").strip()[:80] or "Document"
    day = name_date(f.existing.file_name) if f.existing else None
    cls = DocumentClassification(doc_type=doc_type, title=title, document_date=day, confidence=1.0)
    return cls, (f.existing.model_call_id if f.existing else None)


def _classify(engine: Engine, settings: Settings, f: _Filing) -> tuple[DocumentClassification, UUID]:
    m = f.meta
    prompt = doc_classifier_prompt(m.filename, m.mime_type, m.size_bytes, f.party, f.message_text, f.case_summary)
    result = run_agent(engine, settings, DOC_CLASSIFIER, prompt, CallContext(f.company_id, "doc_classifier"))
    return result.output, result.model_call_id


def _placeholder(f: _Filing) -> DocumentClassification:
    title = (f.meta.filename or "Document").strip()[:80] or "Document"
    return DocumentClassification(doc_type=DocType.other, title=title, document_date=None, confidence=0.0)


def _with_reading(engine: Engine, settings: Settings, storage: ObjectStorage, extractor: TextExtractor,
                  f: _Filing, decision: _Decision) -> _Decision:  # fmt: skip
    """Let the reader refine the metadata decision; any reading failure keeps the metadata decision."""
    m = f.meta
    given = ReadInput(f.company_id, f.attachment_id, m.filename, m.mime_type, m.size_bytes, f.party, f.message_text,
                      f.case_summary)  # fmt: skip
    reading = read_document(engine, settings, storage, extractor, given)
    if reading is None:
        return decision
    return _Decision(reading.facts.as_classification(), reading.call_id, facts_columns(reading), reading.text or None)


def _readable(settings: Settings, extractor: TextExtractor | None, f: _Filing, cls: DocumentClassification) -> bool:
    return (
        extractor is not None
        and settings.doc_read_content
        and cls.doc_type is not DocType.id_document
        and not looks_like_id(f.meta)
    )


def _decide(engine: Engine, settings: Settings, f: _Filing, storage: ObjectStorage,
            extractor: TextExtractor | None) -> _Decision | DocumentStatus:  # fmt: skip
    """Model path for a new or failed row: a final status, or the decision to file."""
    if should_skip(f.meta):
        _upsert(engine, f, _values(f, DocumentStatus.skipped, _placeholder(f)))
        return DocumentStatus.skipped
    try:
        cls, call_id = _classify(engine, settings, f)
    except BudgetExceededError:  # not a classification failure: Harjot's choice files it without an LLM call
        _upsert(engine, f, _values(f, DocumentStatus.review, _placeholder(f)))
        return DocumentStatus.review
    except AgentFailedError as exc:
        _upsert(engine, f, _values(f, DocumentStatus.failed, _placeholder(f), error=str(exc)[:500]))
        return DocumentStatus.failed
    decision = _Decision(cls, call_id)
    if _readable(settings, extractor, f, cls) and extractor is not None:
        decision = _with_reading(engine, settings, storage, extractor, f, decision)
    if filing_status(decision.cls) is DocumentStatus.review or decision.extra.get("suspicious"):
        extra = {"model_call_id": decision.call_id, **decision.extra}
        _upsert(engine, f, _values(f, DocumentStatus.review, decision.cls, **extra), decision.text)
        return DocumentStatus.review
    return decision


def _upload(engine: Engine, f: _Filing, plan: DocumentRow, storage: ObjectStorage, drive: DriveStore) -> None:
    if plan.drive_file_id is None or plan.drive_folder is None:
        raise EstateOSError(f"pending document {plan.id} has no reserved Drive id or folder")
    file_id = drive.find_by_attachment(f.attachment_id)
    if file_id is None:
        folder = drive.ensure_folder(tuple(plan.drive_folder.split("/")))
        content = storage.get(f.s3_key)
        file_id = drive.upload(plan.drive_file_id, folder, plan.file_name, f.meta.mime_type, content, f.attachment_id)
    with Session(engine) as session, session.begin():
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.id == plan.id, DocumentRow.company_id == f.company_id)
            .where(DocumentRow.status == DocumentStatus.pending)
            .values(status=DocumentStatus.filed, drive_file_id=file_id)
        )
    log.info("documents.filed", attachment_id=str(f.attachment_id), doc_type=plan.doc_type)


def _plan(engine: Engine, settings: Settings, f: _Filing, drive: DriveStore, owner_doc_type: DocType | None,
          storage: ObjectStorage, extractor: TextExtractor | None) -> DocumentRow | DocumentStatus:  # fmt: skip
    row = f.existing
    if row is not None and row.status in (*_FINAL, DocumentStatus.pending):
        return row  # final, or an earlier attempt's pending plan: finish it, never classify again
    if owner_doc_type is not None:
        cls, call_id = _owner_choice(f, owner_doc_type)
        return _claim(engine, f, _Decision(cls, call_id), drive.new_file_id())
    if row is not None and row.status is DocumentStatus.review:
        return DocumentStatus.review
    decided = _decide(engine, settings, f, storage, extractor)
    if isinstance(decided, DocumentStatus):
        return decided
    return _claim(engine, f, decided, drive.new_file_id())


def file_document(
    engine: Engine,
    settings: Settings,
    storage: ObjectStorage,
    drive: DriveStore,
    company_id: UUID,
    attachment_id: UUID,
    owner_doc_type: DocType | None = None,
    extractor: TextExtractor | None = None,
) -> DocumentStatus:
    """`extractor=None` files from metadata alone (the M9 behaviour)."""
    f = _load(engine, company_id, attachment_id)
    plan = _plan(engine, settings, f, drive, owner_doc_type, storage, extractor)
    if isinstance(plan, DocumentStatus):
        return plan
    if plan.status in _FINAL:  # already done, possibly by a concurrent caller
        return plan.status
    _upload(engine, f, plan, storage, drive)
    return DocumentStatus.filed


def skip_document(engine: Engine, company_id: UUID, attachment_id: UUID) -> DocumentStatus:
    """Owner chose "skip" on the review card: a review or failed row becomes skipped. Returns the row's status."""
    with Session(engine) as session, session.begin():
        session.execute(
            update(DocumentRow)
            .where(DocumentRow.attachment_id == attachment_id, DocumentRow.company_id == company_id)
            .where(DocumentRow.status.in_(_REOPENABLE))
            .values(status=DocumentStatus.skipped)
        )
        status = session.scalar(
            select(DocumentRow.status).where(
                DocumentRow.attachment_id == attachment_id, DocumentRow.company_id == company_id
            )
        )
    if status is None:
        raise NotFoundError(f"no document for attachment {attachment_id} in company {company_id}")
    return status

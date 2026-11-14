"""Download one version of a BRIXX document file into object storage, idempotently.

Keys are content-addressed per document (`brixx/<company_id>/documents/<document_id>/<sha256>`), so the same bytes
always land on the same object and are written once. `download_version` is the unit a DBOS step retries: a version
already `stored` or `forbidden` is not downloaded again, and no database transaction is held across the BRIXX call.
A 401/403 means the token lacks BRIXX's personal-data permission: the version becomes `forbidden` (surfaced in the
backlog counts) instead of being retried. Only ids, sizes, statuses and error class names are logged; never file
contents or names.
"""

import hashlib
from uuid import UUID

import structlog
from sqlalchemy.orm import Session

from app.channels.brixx.ports import BrixxApi
from app.core.errors import BrixxAuthError, BrixxError
from app.db.enums import BrixxDocumentStatus
from app.directory.brixx.document_state import record_stored, record_unstored, version_row
from app.storage.ports import ObjectStorage, StoredObject, validate_key

log = structlog.get_logger()

DOCUMENT_TABLE = "PRG_DOCUMENT"
CONTENT_TYPE = "application/octet-stream"  # the download API returns bytes only; the real type is not known
_SETTLED = (BrixxDocumentStatus.stored, BrixxDocumentStatus.forbidden)
_HEX = frozenset("0123456789abcdef")


def is_document_table(table: str) -> bool:
    """True for the BRIXX table whose rows are downloadable files."""
    return table.upper() == DOCUMENT_TABLE


def document_key(company_id: UUID, document_id: int, sha256: str) -> str:
    """Storage key of one document's content; the same company, document and bytes always give the same key."""
    if isinstance(document_id, bool) or not isinstance(document_id, int) or document_id < 1:
        raise BrixxError("BRIXX document ids are positive integers")
    if len(sha256) != 64 or not set(sha256) <= _HEX:
        raise ValueError("sha256 must be 64 lowercase hex characters")
    return validate_key(f"brixx/{company_id}/documents/{document_id}/{sha256}")


def fetch_and_store(api: BrixxApi, storage: ObjectStorage, company_id: UUID, document_id: int) -> StoredObject:
    """Download the file and store it under its content key; bytes already stored are not written again.

    `BrixxAuthError` (401/403) and other `BrixxError`s propagate; nothing is stored then.
    """
    document_key(company_id, document_id, "0" * 64)  # validate the id before calling BRIXX
    data = api.download_document(document_id)
    sha256 = hashlib.sha256(data).hexdigest()
    key = document_key(company_id, document_id, sha256)
    if storage.exists(key):
        return StoredObject(key=key, size=len(data), sha256=sha256, content_type=CONTENT_TYPE)
    return storage.put(key, data, CONTENT_TYPE)


def download_version(
    session: Session, api: BrixxApi, storage: ObjectStorage, company_id: UUID, document_id: int, version: str
) -> BrixxDocumentStatus:
    """Download `version` of a document unless it is settled, record the outcome and commit it.

    Returns `stored` or `forbidden`. Any other error propagates for the caller to retry (nothing is recorded); the
    caller records `failed` once it gives up (`record_unstored`).
    """
    known = version_row(session, company_id, document_id, version)
    settled = known.status if known is not None and known.status in _SETTLED else None
    session.rollback()  # no transaction stays open across the BRIXX download
    if settled is not None:
        return settled
    try:
        stored = fetch_and_store(api, storage, company_id, document_id)
    except BrixxAuthError as exc:
        record_unstored(session, company_id, document_id, version, BrixxDocumentStatus.forbidden, type(exc).__name__)
        session.commit()
        log.warning("brixx.document_forbidden", company_id=str(company_id), document_id=document_id)
        return BrixxDocumentStatus.forbidden
    record_stored(session, company_id, document_id, version, stored)
    session.commit()
    log.info("brixx.document_stored", company_id=str(company_id), document_id=document_id, size=stored.size)
    return BrixxDocumentStatus.stored

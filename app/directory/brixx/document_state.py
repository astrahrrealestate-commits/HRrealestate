"""Bookkeeping of BRIXX document downloads (`brixx_documents`): claim, outcome, backlog counts.

A version is claimed (`pending`, attempt 1) before its download workflow is enqueued. A `failed` version is claimed
again (attempt + 1) until `MAX_ATTEMPTS`; `stored` and `forbidden` versions are settled and never claimed again.
Every query filters by `company_id`. Nothing here commits: the caller owns the transaction. `last_error` is an error
class name only.
"""

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.enums import BrixxDocumentStatus
from app.db.models.brixx import BrixxDocument
from app.storage.ports import StoredObject

MAX_ATTEMPTS = 3
_MAX_ERROR = 128
Status = BrixxDocumentStatus


@dataclass(frozen=True)
class Claim:
    document_id: int
    version: str
    attempt: int


def claim_versions(session: Session, company_id: UUID, versions: list[tuple[int, str]]) -> list[Claim]:
    """Mark each (document id, version) `pending` and return the ones to download, with their attempt number.

    New versions start at attempt 1; `failed` ones under `MAX_ATTEMPTS` move back to `pending` with attempt + 1;
    `pending` ones are returned unchanged (their workflow id repeats, so DBOS deduplicates the enqueue).
    """
    versions = list(dict.fromkeys(versions))  # one statement may not touch a row twice
    if not versions:
        return []
    insert = postgresql.insert(BrixxDocument)
    retry = sa.and_(BrixxDocument.status == Status.failed, BrixxDocument.attempts < MAX_ATTEMPTS)
    session.execute(
        insert.values(
            [
                {"id": new_id(), "company_id": company_id, "document_id": d, "source_version": v, "attempts": 1}
                for d, v in versions
            ]
        ).on_conflict_do_update(
            index_elements=["company_id", "document_id", "source_version"],
            set_={
                "status": Status.pending,
                "attempts": BrixxDocument.attempts + 1,
                "last_error": None,
                "updated_at": sa.func.now(),
            },
            where=retry,
        )
    )
    found = _pending_attempts(session, company_id, versions)
    return [Claim(d, v, found[(d, v)]) for d, v in versions if (d, v) in found]


Version = tuple[int, str]  # (document id, source version)


def _pending_attempts(session: Session, company_id: UUID, versions: list[Version]) -> dict[Version, int]:
    rows = session.execute(
        sa.select(BrixxDocument.document_id, BrixxDocument.source_version, BrixxDocument.attempts).where(
            BrixxDocument.company_id == company_id,
            BrixxDocument.document_id.in_(sorted({d for d, _v in versions})),
            BrixxDocument.status == Status.pending,
        )
    ).all()
    wanted = set(versions)
    return {(d, v): a for d, v, a in rows if (d, v) in wanted}


def version_row(session: Session, company_id: UUID, document_id: int, version: str) -> BrixxDocument | None:
    return session.scalars(
        sa.select(BrixxDocument).where(
            BrixxDocument.company_id == company_id,
            BrixxDocument.document_id == document_id,
            BrixxDocument.source_version == version,
        )
    ).one_or_none()


def record_stored(session: Session, company_id: UUID, document_id: int, version: str, obj: StoredObject) -> None:
    """The version's bytes are in storage. Bytes already stored for this document (an earlier version) keep their
    row, which moves to `version`; the claim row is then dropped, so one content never has two rows."""
    claim = version_row(session, company_id, document_id, version)
    content = session.scalars(
        sa.select(BrixxDocument).where(
            BrixxDocument.company_id == company_id,
            BrixxDocument.document_id == document_id,
            BrixxDocument.sha256 == obj.sha256,
        )
    ).one_or_none()
    if content is not None and claim is not None and claim.id != content.id:
        session.delete(claim)
        session.flush()  # free (company, document, version) before the content row takes it
    row = content or claim
    if row is None:
        row = BrixxDocument(company_id=company_id, document_id=document_id, source_version=version, attempts=1)
        session.add(row)
    row.source_version = version
    row.status = Status.stored
    row.sha256, row.storage_key, row.size_bytes, row.content_type = obj.sha256, obj.key, obj.size, obj.content_type
    row.last_error = None
    session.flush()


def record_unstored(
    session: Session, company_id: UUID, document_id: int, version: str, status: BrixxDocumentStatus, error: str
) -> None:
    """Mark the version `forbidden` or `failed` with an error class name. A stored version is never downgraded."""
    if status not in (Status.forbidden, Status.failed):
        raise ValueError(f"not an unstored outcome: {status}")
    row = version_row(session, company_id, document_id, version)
    if row is None:
        row = BrixxDocument(company_id=company_id, document_id=document_id, source_version=version, attempts=1)
        session.add(row)
    elif row.status is Status.stored:
        return
    row.status = status
    row.last_error = error[:_MAX_ERROR]
    session.flush()


def backlog_counts(session: Session, company_id: UUID) -> dict[BrixxDocumentStatus, int]:
    """Document versions per status for one company; every status is present (0 when none)."""
    rows = session.execute(
        sa.select(BrixxDocument.status, sa.func.count())
        .where(BrixxDocument.company_id == company_id)
        .group_by(BrixxDocument.status)
    ).all()
    return counts_by_status([(status, int(count)) for status, count in rows])


def counts_by_status(rows: list[tuple[BrixxDocumentStatus, int]]) -> dict[BrixxDocumentStatus, int]:
    counts = dict.fromkeys(Status, 0)
    for status, count in rows:
        counts[Status(status)] += count
    return counts

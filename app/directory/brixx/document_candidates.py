"""Which mirrored `PRG_DOCUMENT` rows still need a download.

The real PRG_DOCUMENT columns are known only after live discovery, so a row's version is derived from the primary key
table's `versienr` and `upddatetime` columns only (whichever exist). A row is a candidate until its current version is
settled in `brixx_documents`: stored, forbidden, or failed `MAX_ATTEMPTS` times. Rows the reconcile marked deleted
(`_deleted_at`) are skipped. A table without either version column yields one constant version, so a changed file
there is not re-downloaded (known limit until discovery).
"""

from uuid import UUID

import sqlalchemy as sa

from app.core.errors import BrixxError
from app.db.enums import BrixxDocumentStatus
from app.db.models.brixx import BrixxDocument
from app.directory.brixx.document_state import MAX_ATTEMPTS
from app.directory.brixx.schema import INCREMENTAL_COLUMN
from app.directory.brixx.upsert import VERSION_COLUMN

_VERSION_LENGTH = 128  # brixx_documents.source_version
_NO_VERSION = "-"


def _as_text(column: sa.ColumnElement[object]) -> sa.ColumnElement[str]:
    """A deterministic text form: timestamps in UTC, never in the session time zone."""
    if isinstance(column.type, sa.DateTime):
        utc = sa.func.timezone("UTC", column)
        return sa.func.to_char(utc, sa.literal('YYYY-MM-DD"T"HH24:MI:SS.US'), type_=sa.Text)
    if isinstance(column.type, sa.Date):
        return sa.func.to_char(column, sa.literal("YYYY-MM-DD"), type_=sa.Text)
    return sa.cast(column, sa.Text)


def version_expression(table: sa.Table) -> sa.ColumnElement[str]:
    """`v<versienr>|u<upddatetime>` from the columns the table has, or `-` when it has neither."""
    parts: list[sa.ColumnElement[str]] = []
    for prefix, name in (("v", VERSION_COLUMN), ("u", INCREMENTAL_COLUMN)):
        if name in table.c:
            parts.append(sa.func.concat(prefix, sa.func.coalesce(_as_text(table.c[name]), ""), type_=sa.Text))
    if not parts:
        return sa.literal(_NO_VERSION, type_=sa.Text)
    joined = parts[0] if len(parts) == 1 else sa.func.concat_ws("|", *parts, type_=sa.Text)
    return sa.func.left(joined, _VERSION_LENGTH, type_=sa.Text)


def candidates_query(table: sa.Table, company_id: UUID, limit: int) -> sa.Select[int, str]:
    """(document id, version) of up to `limit` live rows of one company whose version is not settled, by key."""
    if limit < 1:
        raise BrixxError("candidate limit must be positive")
    pk = table.c[_primary_key(table)]
    version = version_expression(table).label("version")
    doc = BrixxDocument
    settled = sa.or_(
        doc.status.in_([BrixxDocumentStatus.stored, BrixxDocumentStatus.forbidden]),
        sa.and_(doc.status == BrixxDocumentStatus.failed, doc.attempts >= MAX_ATTEMPTS),
    )
    done = sa.exists().where(
        doc.company_id == company_id, doc.document_id == pk, doc.source_version == version_expression(table), settled
    )
    return (
        sa.select(pk, version)
        .where(table.c.company_id == company_id, table.c["_deleted_at"].is_(None), ~done)
        .order_by(pk)
        .limit(limit)
    )


def _primary_key(table: sa.Table) -> str:
    keys = [c.name for c in table.primary_key.columns if c.name != "company_id"]
    if len(keys) != 1:
        raise BrixxError(f"mirror table {table.name!r} needs exactly one BRIXX primary key column")
    return keys[0]

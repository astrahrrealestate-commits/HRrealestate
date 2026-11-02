"""Build the SQLAlchemy mirror table for one BRIXX table.

Tables go into the caller's `MetaData` (never `Base.metadata`), so the Alembic drift check ignores them. BRIXX names
come from an external API and end up in DDL and SQL, so they are validated before anything is built.
"""

import hashlib
import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxError

MIRROR_SCHEMA = "brixx"
SYSTEM_COLUMNS = frozenset({"company_id", "_synced_at", "_deleted_at", "_extra"})
INCREMENTAL_COLUMN = "upddatetime"

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_MAX_IDENTIFIER = 63
_VARCHAR = re.compile(r"^VARCHAR2?\s*\(\s*(\d+)")


def sql_type(brixx_type: str, *, is_key: bool) -> sa.types.TypeEngine[Any]:
    """Map a BRIXX column type to a Postgres type; key NUMBERs are BigInteger, anything unknown is Text."""
    upper = brixx_type.strip().upper()
    if upper.startswith("NUMBER"):
        return sa.BigInteger() if is_key else sa.Numeric()
    varchar = _VARCHAR.match(upper)
    if varchar:
        return sa.String(int(varchar.group(1)))
    if upper == "DATE":
        return sa.Date()
    if upper.startswith(("TIMESTAMP", "DATETIME")):
        return sa.DateTime(timezone=True)
    return sa.Text()


def has_incremental_column(info: BrixxTable) -> bool:
    """True when the table carries `UPDDATETIME` (any case), which enables incremental sync."""
    return any(f.name.lower() == INCREMENTAL_COLUMN for f in info.fields)


def build_table(info: BrixxTable, metadata: sa.MetaData) -> sa.Table:
    """Create `brixx.<table>` in `metadata`: BRIXX columns lower-cased plus system columns, PK (company_id, pk)."""
    table_name = _safe_identifier(info.name, "table")
    pk = _safe_identifier(info.primary_key, "primary key").lower()
    fields = _validated_fields(info)
    if pk not in fields:
        raise BrixxError(f"primary key {info.primary_key!r} is not a column of BRIXX table {info.name!r}")
    columns: list[sa.Column[Any]] = [sa.Column("company_id", sa.Uuid(), nullable=False)]
    columns.extend(_data_column(name, field, pk) for name, field in fields.items())
    columns.extend(_system_columns())
    table = sa.Table(
        table_name.lower(), metadata, *columns, sa.PrimaryKeyConstraint("company_id", pk), schema=MIRROR_SCHEMA
    )
    for column in _indexed_columns(fields):
        sa.Index(_index_name(table.name, column), table.c[column])
    return table


def _safe_identifier(name: str, kind: str) -> str:
    if len(name) > _MAX_IDENTIFIER or not _IDENTIFIER.fullmatch(name):
        raise BrixxError(f"unsafe BRIXX {kind} name {name!r}")
    return name


def _validated_fields(info: BrixxTable) -> dict[str, BrixxField]:
    fields: dict[str, BrixxField] = {}
    for field in info.fields:
        lowered = _safe_identifier(field.name, "column").lower()
        if lowered in SYSTEM_COLUMNS:
            raise BrixxError(f"BRIXX column {field.name!r} in {info.name!r} collides with a mirror system column")
        if lowered in fields:
            raise BrixxError(f"BRIXX table {info.name!r} has duplicate column {lowered!r} after lower-casing")
        fields[lowered] = field
    return fields


def _data_column(name: str, field: BrixxField, pk: str) -> sa.Column[Any]:
    is_key = name == pk or name.endswith("id") or field.fk_table is not None
    return sa.Column(name, sql_type(field.type, is_key=is_key), nullable=name != pk)


def _system_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("_extra", JSONB(), nullable=True),
    ]


def _indexed_columns(fields: dict[str, BrixxField]) -> list[str]:
    return [n for n, f in fields.items() if f.fk_table is not None or n == INCREMENTAL_COLUMN]


def _index_name(table: str, column: str) -> str:
    name = f"ix_{table}_{column}"
    if len(name) <= _MAX_IDENTIFIER:
        return name
    suffix = hashlib.sha1(name.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"{name[: _MAX_IDENTIFIER - 9]}_{suffix}"

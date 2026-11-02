"""Idempotent page upsert into a BRIXX mirror table.

One `INSERT ... ON CONFLICT (company_id, pk) DO UPDATE` per chunk of a page. The conflict update is guarded so a
replayed or out-of-order page never overwrites a newer stored row. The caller owns the transaction: nothing here
commits. Row values and keys are never logged.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxTable
from app.channels.brixx.normalise import normalise_row
from app.core.errors import BrixxError
from app.directory.brixx.schema import INCREMENTAL_COLUMN, SYSTEM_COLUMNS

log = structlog.get_logger()

MAX_BIND_PARAMS = 65_535
_RESERVED_PARAMS = 64
VERSION_COLUMN = "versienr"


@dataclass(frozen=True)
class UpsertResult:
    written: int
    skipped_older: int
    extra_columns: frozenset[str]


def chunk_size(params_per_row: int) -> int:
    """Rows per statement so that one INSERT stays under the Postgres bind-parameter limit."""
    return max(1, (MAX_BIND_PARAMS - _RESERVED_PARAMS) // params_per_row)


def upsert_page(
    session: Session,
    table: sa.Table,
    info: BrixxTable,
    company_id: UUID,
    rows: list[dict[str, object]],
    synced_at: datetime,
) -> UpsertResult:
    """Write a page of BRIXX rows for one company.

    Precondition: every row carries every mirror column (full replacement; never fetch with a `fields=` projection),
    because absent columns are written as NULL. `skipped_older` counts rows not written: in-page duplicates that a
    higher version superseded, plus rows a newer stored row beat. Nothing is committed here.
    """
    if synced_at.utcoffset() is None:
        raise BrixxError("synced_at must be timezone-aware")
    pk = info.primary_key.lower()
    data_columns = [c.name for c in table.c if c.name not in SYSTEM_COLUMNS | {"_synced_at"}]
    records: dict[int, dict[str, object]] = {}
    extra_columns: set[str] = set()
    for raw in rows:
        values, extras = _split_row(raw, data_columns)
        key = _primary_key(values.get(pk), info.name)
        values[pk] = key
        extra_columns.update(extras)
        values["_extra"] = extras or None
        current = records.get(key)
        records[key] = values if current is None or _supersedes(values, current) else current
    written = _write_chunks(session, table, pk, company_id, list(records.values()), synced_at)
    log.info("brixx.upsert", table=table.name, rows=len(rows), written=written, extra_columns=len(extra_columns))
    return UpsertResult(written, len(rows) - written, frozenset(extra_columns))


def _primary_key(value: object, table_name: str) -> int:
    """BRIXX primary keys are integers; `1`, `"1"` and `1.0` are the same row. Never echoes the value."""
    if isinstance(value, bool) or value is None:
        raise BrixxError(f"row for BRIXX table {table_name!r} has a missing or invalid primary key")
    try:
        if isinstance(value, float | Decimal):
            if value != int(value):
                raise ValueError
            return int(value)
        if isinstance(value, int | str):
            return int(value)
    except (ValueError, OverflowError):
        pass
    raise BrixxError(f"row for BRIXX table {table_name!r} has a missing or invalid primary key")


def _split_row(raw: dict[str, object], data_columns: list[str]) -> tuple[dict[str, object], dict[str, object]]:
    lowered = {key.lower(): value for key, value in normalise_row(raw).items()}
    values = {name: lowered.pop(name, None) for name in data_columns}
    return values, lowered


def _supersedes(new: dict[str, object], old: dict[str, object]) -> bool:
    """Within one page, the higher (versienr, upddatetime) wins; incomparable or equal values: the later row wins."""
    try:
        return _order(new) >= _order(old)
    except TypeError:
        return True


def _order(values: dict[str, object]) -> tuple[Any, ...]:
    version = values.get(VERSION_COLUMN)
    updated = values.get(INCREMENTAL_COLUMN)
    return (version is not None, version, updated is not None, updated)


def _write_chunks(
    session: Session,
    table: sa.Table,
    pk: str,
    company_id: UUID,
    records: list[dict[str, object]],
    synced_at: datetime,
) -> int:
    if not records:
        return 0
    size = chunk_size(len(records[0]) + 2)  # data columns + _extra, plus company_id and _synced_at
    statement = _upsert_statement(table, pk)
    written = 0
    for start in range(0, len(records), size):
        chunk = [{**r, "company_id": company_id, "_synced_at": synced_at} for r in records[start : start + size]]
        written += len(session.execute(statement.values(chunk)).all())
    return written


def _upsert_statement(table: sa.Table, pk: str) -> sa.Insert:
    insert = postgresql.insert(table)
    updatable = [c.name for c in table.c if c.name not in {"company_id", pk, "_deleted_at"}]
    set_: dict[str, Any] = {name: insert.excluded[name] for name in updatable}
    set_["_deleted_at"] = None
    return insert.on_conflict_do_update(
        index_elements=[table.c.company_id, table.c[pk]],
        set_=set_,
        where=_write_guard(table, insert.excluded),
    ).returning(table.c[pk])


def _write_guard(table: sa.Table, excluded: Any) -> sa.ColumnElement[bool]:
    """True when the incoming row may replace the stored one; tables without ordering columns always do.

    NULL ranks as oldest, matching the in-page order: it loses to a non-NULL value but never to another NULL.
    """
    has_version = VERSION_COLUMN in table.c
    skips: list[sa.ColumnElement[bool]] = []
    if has_version:
        skips.append(_older(table.c[VERSION_COLUMN], excluded[VERSION_COLUMN]))
    if INCREMENTAL_COLUMN in table.c:
        stale = _older(table.c[INCREMENTAL_COLUMN], excluded[INCREMENTAL_COLUMN])
        if has_version:
            same_version = table.c[VERSION_COLUMN].is_not_distinct_from(excluded[VERSION_COLUMN])
            stale = sa.and_(same_version, stale)
        skips.append(stale)
    return sa.not_(sa.or_(*skips)) if skips else sa.true()


def _older(stored: Any, incoming: Any) -> sa.ColumnElement[bool]:
    """True (never NULL) when the incoming value ranks strictly below the stored one."""
    return sa.or_(
        sa.and_(stored.is_not(None), incoming.is_(None)),
        sa.and_(stored.is_not(None), incoming.is_not(None), stored > incoming),
    )

"""Reconcile one mirrored BRIXX table against BRIXX's full primary-key list (spec 2026-10-31, daily reconcile).

`scan_page` fetches one keyset page of primary keys only (`fields=<pk>`, `[<pk> > cursor]`, ordered by pk, always
page 1), so a hard delete during the scan cannot shift a page and hide a key. The keys are staged in
`brixx_reconcile_seen` and committed with the page (a replayed step inserts nothing new).
`apply_reconcile` then, in one transaction: soft-deletes (`_deleted_at`) mirror rows BRIXX no longer lists, but only
rows synced before the run started (an incremental sync may add rows mid-scan); clears `_deleted_at` on rows BRIXX
lists again; counts keys BRIXX has and the mirror lacks and, if there are any, resets the table watermark so the next
incremental run fetches the whole table (backfill); finally deletes the staged keys. `INDVERWIJDERD=1` rows are
BRIXX's own soft delete and are left alone: BRIXX still lists them. Only counts and table names are logged.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxTable
from app.channels.brixx.ports import BrixxApi
from app.channels.brixx.query import build_filter
from app.core.errors import BrixxError
from app.db.models.brixx_directory import BrixxReconcileSeen
from app.directory.brixx.state import get_or_create_table_state
from app.directory.brixx.upsert import primary_key

log = structlog.get_logger()


@dataclass(frozen=True)
class ScanResult:
    cursor: int | None  # highest primary key staged so far
    has_next: bool
    seen: int


@dataclass(frozen=True)
class ReconcileResult:
    soft_deleted: int
    restored: int
    missing: int


def keyset_filter(pk: str, cursor: int | None) -> str | None:
    return None if cursor is None else build_filter((pk, ">", cursor))


def scan_page(
    session: Session, api: BrixxApi, company_id: UUID, info: BrixxTable, run_id: UUID, cursor: int | None
) -> ScanResult:
    """Fetch and stage the next keyset page of primary keys after `cursor`, then commit. A row with no usable
    primary key value (seen in some historical `Z*` rows) is skipped, not fatal to the rest of the page."""
    pk = info.primary_key.lower()
    page = api.fetch_page(info.name, page=1, filters=keyset_filter(pk, cursor), order_by=pk, fields=(info.primary_key,))
    valid_keys: set[int] = set()
    bad_pk = 0
    for row in page.rows:
        try:
            valid_keys.add(primary_key(_cell(row, pk), info.name))
        except BrixxError:
            bad_pk += 1
    if bad_pk:
        log.warning("brixx.reconcile_scan_skipped_bad_pk", table=info.name, count=bad_pk)
    keys = sorted(valid_keys)
    if page.has_next and (not keys or (cursor is not None and keys[-1] <= cursor)):
        raise BrixxError(f"keyset scan of BRIXX table {info.name!r} made no progress")
    if keys:
        session.execute(
            postgresql.insert(BrixxReconcileSeen)
            .values([{"company_id": company_id, "run_id": run_id, "table_name": info.name, "pk": k} for k in keys])
            .on_conflict_do_nothing(index_elements=["company_id", "run_id", "table_name", "pk"])
        )
    session.commit()
    return ScanResult(keys[-1] if keys else cursor, page.has_next, len(keys))


def _cell(row: dict[str, object], column: str) -> object:
    return next((value for key, value in row.items() if key.lower() == column), None)


def _seen(company_id: UUID, run_id: UUID, table_name: str) -> sa.Select[int]:
    return sa.select(BrixxReconcileSeen.pk).where(
        BrixxReconcileSeen.company_id == company_id,
        BrixxReconcileSeen.run_id == run_id,
        BrixxReconcileSeen.table_name == table_name,
    )


def _count_missing(session: Session, seen: sa.Select[int], mirrored: sa.Select[int]) -> int:
    absent = seen.where(BrixxReconcileSeen.pk.not_in(mirrored)).subquery()
    return int(session.scalar(sa.select(sa.func.count()).select_from(absent)) or 0)


def apply_reconcile(
    session: Session,
    company_id: UUID,
    info: BrixxTable,
    table: sa.Table,
    *,
    run_id: UUID,
    run_started_at: datetime,
    now: datetime,
) -> ReconcileResult:
    """Soft-delete, restore and count missing keys for one table from the staged keys of `run_id`; commits."""
    key = table.c[info.primary_key.lower()]
    seen = _seen(company_id, run_id, info.name)
    mine = table.c.company_id == company_id
    deleted = session.execute(
        sa.update(table)
        .where(mine, table.c._deleted_at.is_(None), table.c._synced_at < run_started_at, key.not_in(seen))
        .values(_deleted_at=now)
    )
    restored = session.execute(
        sa.update(table).where(mine, table.c._deleted_at.is_not(None), key.in_(seen)).values(_deleted_at=None)
    )
    missing = _count_missing(session, seen, sa.select(key).where(mine))
    if missing:
        get_or_create_table_state(session, company_id, info.name).last_success_upd = None
    session.execute(
        sa.delete(BrixxReconcileSeen).where(
            BrixxReconcileSeen.company_id == company_id,
            BrixxReconcileSeen.run_id == run_id,
            BrixxReconcileSeen.table_name == info.name,
        )
    )
    session.commit()
    result = ReconcileResult(int(getattr(deleted, "rowcount", 0)), int(getattr(restored, "rowcount", 0)), missing)
    log.info("brixx.reconcile_table", table=info.name, **result.__dict__)
    return result

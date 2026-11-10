"""GDPR erasure of a BRIXX relatie: tombstone, mirror purge, and the tombstone check the mirror upsert uses.

Lives below `app.pipeline` (the erasure cascade) and `app.directory` (the upsert and the mapper), which may not import
each other. The tombstone and the purge share one transaction with a per-company advisory lock; the upsert takes the
same lock shared, so an in-flight page can never write an erased relatie back after the purge commits. A missing
mirror table (the Phase B migration has not run) purges nothing; the tombstone is still recorded.
"""

from typing import Any
from uuid import UUID

import psycopg.errors
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.db.models.brixx_directory import BrixxErasedRef

MIRROR_SCHEMA = "brixx"
RELATIE_KEY = "prg_relatieid"
RELATIE_TABLES = frozenset({"prg_relatie", "zprg_relatie"})  # mirror tables whose rows belong to one relatie


def _lock(session: Session, company_id: UUID, *, shared: bool) -> None:
    key = sa.func.hashtextextended(f"brixx-erasure:{company_id}", 0)
    lock = sa.func.pg_advisory_xact_lock_shared if shared else sa.func.pg_advisory_xact_lock
    session.execute(sa.select(lock(key)))


def erased_relatie_ids(session: Session, company_id: UUID) -> set[int]:
    query = sa.select(BrixxErasedRef.relatie_id).where(BrixxErasedRef.company_id == company_id)
    return set(session.scalars(query))


def relatie_id(value: object) -> int | None:
    """A relatie id from a mirror cell or a `brixx_ref` string; None when it is not an integer."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def purge_brixx_relatie(session: Session, company_id: UUID, relatie: int) -> int:
    """Tombstone `relatie` and delete its mirror rows (current and history). Idempotent; the caller commits."""
    _lock(session, company_id, shared=False)
    session.execute(
        postgresql.insert(BrixxErasedRef)
        .values(company_id=company_id, relatie_id=relatie)
        .on_conflict_do_nothing(index_elements=["company_id", "relatie_id"])
    )
    return sum(_delete_rows(session, name, company_id, relatie) for name in sorted(RELATIE_TABLES))


def mirror_table(name: str, *columns: sa.Column[Any]) -> sa.Table:
    """A partial `brixx.<name>` (company_id plus `columns`): a real `Table`, so `schema_translate_map` applies."""
    return sa.Table(name, sa.MetaData(), sa.Column("company_id", sa.Uuid()), *columns, schema=MIRROR_SCHEMA)


def _delete_rows(session: Session, name: str, company_id: UUID, relatie: int) -> int:
    table = mirror_table(name, sa.Column(RELATIE_KEY, sa.BigInteger()))
    statement = sa.delete(table).where(table.c.company_id == company_id, table.c[RELATIE_KEY] == relatie)
    try:
        with session.begin_nested():
            result = session.execute(statement)
    except ProgrammingError as exc:
        if isinstance(exc.orig, psycopg.errors.UndefinedTable | psycopg.errors.InvalidSchemaName):
            return 0
        raise
    return int(getattr(result, "rowcount", 0))


def without_erased(
    session: Session, table_name: str, company_id: UUID, records: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Drop rows of erased relaties from a page bound for `table_name` (other tables pass through untouched)."""
    if table_name.lower() not in RELATIE_TABLES:
        return records
    _lock(session, company_id, shared=True)
    erased = erased_relatie_ids(session, company_id)
    if not erased:
        return records
    return [r for r in records if relatie_id(r.get(RELATIE_KEY)) not in erased]

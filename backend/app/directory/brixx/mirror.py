"""Which BRIXX columns the sync may write: the ones the migrated mirror table really has, with the same type.

Mirror tables are created by generated Alembic revisions from the metadata snapshot, so the database catalog is the
runtime copy of that snapshot (the image ships no fixtures). Live metadata is narrowed to the columns the mirror
stores with an identical Postgres type; anything else (a new BRIXX column, a changed type) is left to `_extra` by the
upsert and the table is flagged drifted. A table that does not exist yet, or lacks its primary key or the system
columns, is not storable at all: the sync skips it as drifted instead of failing the run.
"""

import sqlalchemy as sa
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxTable
from app.directory.brixx.schema import SYSTEM_COLUMNS, build_table


def mirror_columns(session: Session, info: BrixxTable) -> dict[str, str] | None:
    """Column name -> compiled type of the mirror table for `info`, or None when it does not exist.

    Honours the connection's `schema_translate_map` (tests redirect `brixx` to a throwaway schema). Catalog only:
    no row is read.
    """
    probe = build_table(info, sa.MetaData())  # validates the names before they reach the catalog query
    connection = session.connection()
    schema = connection.schema_for_object(probe)
    inspector = sa.inspect(connection)
    if not inspector.has_table(probe.name, schema=schema):
        return None
    dialect = connection.dialect
    return {c["name"]: c["type"].compile(dialect=dialect) for c in inspector.get_columns(probe.name, schema=schema)}


def storable(info: BrixxTable, mirror: dict[str, str] | None, dialect: Dialect) -> BrixxTable | None:
    """`info` narrowed to the fields the mirror stores as-is, or None when the mirror cannot take rows at all."""
    if mirror is None or not mirror.keys() >= SYSTEM_COLUMNS:
        return None
    built = build_table(info, sa.MetaData())
    keep = {c.name for c in built.c if c.name not in SYSTEM_COLUMNS and mirror.get(c.name) == _kind(c, dialect)}
    if info.primary_key.lower() not in keep:
        return None
    return BrixxTable(info.name, info.primary_key, tuple(f for f in info.fields if f.name.lower() in keep))


def _kind(column: sa.Column[object], dialect: Dialect) -> str:
    return column.type.compile(dialect=dialect)

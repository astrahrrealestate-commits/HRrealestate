"""Shared BRIXX mirror integration setup: mirror tables in a uniquely named throwaway schema.

The real `brixx` schema is created by a migration (Phase B), so tests must never create or drop a schema literally
named `brixx`. `build_table` still targets `brixx`; a `schema_translate_map` redirects it to the throwaway schema.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxField, BrixxTable
from app.directory.brixx.schema import MIRROR_SCHEMA, build_table


@dataclass(frozen=True)
class MirrorSchema:
    name: str
    engine: Engine

    def create(self, info: BrixxTable) -> sa.Table:
        metadata = sa.MetaData()
        table = build_table(info, metadata)
        metadata.create_all(self.engine)
        return table

    def session(self) -> Session:
        return Session(bind=self.engine)


@contextmanager
def mirror_schema(engine: Engine) -> Iterator[MirrorSchema]:
    name = f"brixx_t_{uuid.uuid4().hex[:12]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{name}"'))
    try:
        yield MirrorSchema(name, engine.execution_options(schema_translate_map={MIRROR_SCHEMA: name}))
    finally:
        with engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA IF EXISTS "{name}" CASCADE'))


def versioned_table_info() -> BrixxTable:
    """A table with the ordering columns the upsert guard uses."""
    return BrixxTable(
        "PRG_DEMO",
        "ID",
        (
            BrixxField(1, "ID", "NUMBER", True, None, None),
            BrixxField(2, "NAAM", "VARCHAR(50)", False, None, None),
            BrixxField(3, "VERSIENR", "NUMBER", False, None, None),
            BrixxField(4, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
        ),
    )


def plain_table_info() -> BrixxTable:
    """A table without versienr/upddatetime: every write overwrites."""
    return BrixxTable(
        "PRG_PLAIN",
        "ID",
        (
            BrixxField(1, "ID", "NUMBER", True, None, None),
            BrixxField(2, "NAAM", "VARCHAR(50)", False, None, None),
        ),
    )

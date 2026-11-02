"""The mirror DDL is valid on real Postgres and round-trips a row."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from app.channels.brixx.models import BrixxField, BrixxTable
from app.directory.brixx.schema import MIRROR_SCHEMA, build_table


@pytest.fixture
def mirror_schema(migrated_engine: Engine) -> Iterator[None]:
    with migrated_engine.begin() as conn:
        conn.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {MIRROR_SCHEMA}"))
    yield
    with migrated_engine.begin() as conn:
        conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {MIRROR_SCHEMA} CASCADE"))


def test_create_all_insert_and_read_back(migrated_engine: Engine, mirror_schema: None) -> None:
    info = BrixxTable(
        "PRG_RELATIE",
        "PRG_RELATIEID",
        (
            BrixxField(1, "PRG_RELATIEID", "NUMBER", True, None, None),
            BrixxField(2, "NAAM", "VARCHAR(132)", False, None, None),
            BrixxField(3, "OBJECTID", "NUMBER", False, "PRG_OBJECT", "PRG_OBJECTID"),
            BrixxField(4, "SALDO", "NUMBER", False, None, None),
            BrixxField(5, "GEBOREN", "DATE", False, None, None),
            BrixxField(6, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
        ),
    )
    metadata = sa.MetaData()
    table = build_table(info, metadata)
    metadata.create_all(migrated_engine)
    company_id = uuid.uuid4()
    updated = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    with migrated_engine.begin() as conn:
        conn.execute(
            sa.insert(table).values(
                company_id=company_id,
                prg_relatieid=9_000_000_000,
                naam="Jansen",
                objectid=7,
                saldo=Decimal("12.345678"),
                upddatetime=updated,
                _extra={"x": 1},
            )
        )
        row = conn.execute(sa.select(table).where(table.c.company_id == company_id)).one()
    assert row.prg_relatieid == 9_000_000_000
    assert row.naam == "Jansen"
    assert row.saldo == Decimal("12.345678")
    assert row.upddatetime == updated
    assert row._deleted_at is None
    assert row._synced_at is not None
    assert row._extra == {"x": 1}
    with migrated_engine.connect() as conn:
        indexes = {i["name"] for i in sa.inspect(conn).get_indexes("prg_relatie", schema=MIRROR_SCHEMA)}
    assert indexes == {"ix_prg_relatie_objectid", "ix_prg_relatie_upddatetime"}

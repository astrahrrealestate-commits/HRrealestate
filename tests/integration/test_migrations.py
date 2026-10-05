import re
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, make_url, text

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch_db_url(pg_url: str) -> Iterator[str]:
    """A separate database on the session container, so a failed round-trip cannot break other tests."""
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip"))
        conn.execute(text("CREATE DATABASE roundtrip"))
    yield make_url(pg_url).set(database="roundtrip").render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip WITH (FORCE)"))
    admin.dispose()


def test_roundtrip(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    try:
        for _ in range(2):
            command.upgrade(cfg, "head")
            assert set(inspect(engine).get_table_names()) >= set(Base.metadata.tables)
            command.downgrade(cfg, "base")
            assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_drift(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_every_enum_column_check_matches_model_values(migrated_engine: Engine) -> None:
    """Autogenerate drift ignores CHECKs: a new StrEnum value without a migration would only fail at runtime."""
    insp = inspect(migrated_engine)
    for table in Base.metadata.sorted_tables:
        checks = {ck["name"]: ck["sqltext"] for ck in insp.get_check_constraints(table.name)}
        for col in table.c:
            if not isinstance(col.type, sa.Enum):
                continue
            name = f"ck_{table.name}_{col.name}"
            assert name in checks, f"missing CHECK {name}"
            allowed = set(re.findall(r"'([^']*)'", checks[name]))
            assert allowed == set(col.type.enums), f"{name}: db {sorted(allowed)} != model {sorted(col.type.enums)}"

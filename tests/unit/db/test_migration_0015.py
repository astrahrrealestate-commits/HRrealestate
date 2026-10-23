"""Migration 0015 and the model describe the same `agent_page_state` table (the drift test needs Docker)."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base

VERSIONS = Path(__file__).resolve().parents[3] / "app/db/alembic/versions"
TABLE = "agent_page_state"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0015", VERSIONS / "0015_agent_page_state.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _created() -> tuple[sa.Table, list[str]]:
    """The table the migration creates, built on a scratch MetaData, and the index names it adds."""
    m = _migration()
    with patch.object(m, "op") as op:
        op.f.side_effect = lambda name: name
        m.upgrade()
    name, *items = op.create_table.call_args.args
    scratch = sa.MetaData()
    for parent in ("companies", "owner_accounts"):  # FK targets, so the DDL compiles
        sa.Table(parent, scratch, sa.Column("id", sa.Uuid(), primary_key=True))
    table = sa.Table(name, scratch, *items)
    return table, [c.args[0] for c in op.create_index.call_args_list]


def test_revision_follows_0014() -> None:
    m = _migration()
    assert (m.revision, m.down_revision) == ("0015", "0014")


def test_columns_types_and_nullability_match_the_model() -> None:
    table, _ = _created()
    model = Base.metadata.tables[TABLE]
    assert set(table.c.keys()) == set(model.c.keys()) == {
        "id", "company_id", "owner_id", "page_key", "resolved", "resolved_at", "created_at",
    }  # fmt: skip
    for column in model.c:
        migrated = table.c[column.name]
        assert migrated.nullable == column.nullable is False, column.name
        assert type(migrated.type) is type(column.type), column.name
    assert isinstance(table.c.resolved.type, postgresql.JSONB)
    assert isinstance(table.c.resolved_at.type, sa.DateTime)
    assert table.c.resolved_at.type.timezone is True
    assert "snapshot" not in table.c
    assert "page_context" not in table.c


def test_constraints_and_index_names_match_the_naming_convention() -> None:
    table, indexes = _created()
    model = Base.metadata.tables[TABLE]
    model_ddl = str(CreateTable(model).compile(dialect=postgresql.dialect()))
    migrated_ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    for name in (
        "pk_agent_page_state",
        "uq_agent_page_state_owner_id",
        "fk_agent_page_state_company_id_companies",
        "fk_agent_page_state_owner_id_owner_accounts",
    ):
        assert f"CONSTRAINT {name} " in model_ddl, name
        assert f"CONSTRAINT {name} " in migrated_ddl, name
    assert "UNIQUE (owner_id)" in model_ddl
    assert "UNIQUE (owner_id)" in migrated_ddl
    assert "ON DELETE RESTRICT" in migrated_ddl
    (model_index,) = model.indexes
    assert indexes == [model_index.name] == ["ix_agent_page_state_company_id"]
    assert str(CreateIndex(model_index).compile(dialect=postgresql.dialect())) == (
        "CREATE INDEX ix_agent_page_state_company_id ON agent_page_state (company_id)"
    )


def test_downgrade_drops_the_table() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        op.f.side_effect = lambda name: name
        m.downgrade()
    assert op.drop_index.call_args.args == ("ix_agent_page_state_company_id",)
    assert op.drop_table.call_args.args == (TABLE,)

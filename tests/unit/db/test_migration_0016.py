"""Migration 0016 and the models describe the same freshness indexes (the drift test needs Docker)."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import app.db.models  # noqa: F401  (registers tables)
from app.db.base import Base

VERSIONS = Path(__file__).resolve().parents[3] / "app/db/alembic/versions"
EXPECTED = {
    ("ix_messages_company_id_messages_created_at", "messages", ("company_id", "created_at")),
    ("ix_approvals_company_id_approvals_created_at", "approvals", ("company_id", "created_at")),
    ("ix_approvals_company_id_approvals_decided_at", "approvals", ("company_id", "decided_at")),
    ("ix_case_events_company_id_case_events_created_at", "case_events", ("company_id", "created_at")),
}
DROPPED = {("ix_approvals_company_id", "approvals"), ("ix_case_events_company_id", "case_events")}


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0016", VERSIONS / "0016_page_state_freshness.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_follows_0015() -> None:
    m = _migration()
    assert (m.revision, m.down_revision) == ("0016", "0015")


def test_upgrade_creates_the_model_indexes_and_drops_the_redundant_ones() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        op.f.side_effect = lambda name: name
        m.upgrade()
    created = {(c.args[0], c.args[1], tuple(c.args[2])) for c in op.create_index.call_args_list}
    assert created == EXPECTED
    assert all(c.kwargs == {"unique": False} for c in op.create_index.call_args_list)
    assert {(c.args[0], c.kwargs["table_name"]) for c in op.drop_index.call_args_list} == DROPPED
    for name, table, columns in EXPECTED:
        (index,) = [i for i in Base.metadata.tables[table].indexes if i.name == name]
        ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        assert ddl == f"CREATE INDEX {name} ON {table} ({', '.join(columns)})"
    for name, table in DROPPED:
        assert name not in {i.name for i in Base.metadata.tables[table].indexes}


def test_downgrade_restores_the_single_column_indexes_and_drops_the_new_ones() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        op.f.side_effect = lambda name: name
        m.downgrade()
    restored = {(c.args[0], c.args[1], tuple(c.args[2])) for c in op.create_index.call_args_list}
    assert restored == {(name, table, ("company_id",)) for name, table in DROPPED}
    dropped = {(c.args[0], c.kwargs["table_name"]) for c in op.drop_index.call_args_list}
    assert dropped == {(name, table) for name, table, _ in EXPECTED}

"""Migration 0012 and the models describe the same thread index and timings column (the drift test needs Docker)."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch
from uuid import UUID

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

import app.db.models  # noqa: F401  (registers tables)
from app.contracts import Channel
from app.db.base import Base
from app.db.models.ingestion import THREAD_KEY_SQL
from app.pipeline import page_memory

VERSIONS = Path(__file__).resolve().parents[3] / "app/db/alembic/versions"
NAME = "ix_messages_company_channel_thread"


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0012", VERSIONS / "0012_turn_timings_thread_index.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_follows_0011() -> None:
    m = _migration()
    assert (m.revision, m.down_revision) == ("0012", "0011")


def test_migration_and_model_build_the_same_thread_index() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        m.upgrade()
    name, table, columns = op.create_index.call_args.args
    assert (name, table) == (NAME, "messages")
    assert [str(c) for c in columns] == ["company_id", "channel", THREAD_KEY_SQL]
    (model_index,) = [i for i in Base.metadata.tables["messages"].indexes if i.name == NAME]
    ddl = str(CreateIndex(model_index).compile(dialect=postgresql.dialect()))
    assert ddl == f"CREATE INDEX {NAME} ON messages (company_id, channel, {THREAD_KEY_SQL})"


def test_timings_column_is_nullable_jsonb_in_both() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        m.upgrade()
    table, column = op.add_column.call_args.args
    assert (table, column.name, column.nullable, type(column.type)) == (
        "agent_turns",
        "timings",
        True,
        postgresql.JSONB,
    )
    model = Base.metadata.tables["agent_turns"].c.timings
    assert model.nullable
    assert isinstance(model.type, postgresql.JSONB)


def test_downgrade_drops_both() -> None:
    m = _migration()
    with patch.object(m, "op") as op:
        m.downgrade()
    assert op.drop_index.call_args.args == (NAME,)
    assert op.drop_column.call_args.args == ("agent_turns", "timings")


def test_the_thread_page_query_filters_on_the_indexed_columns_and_expression() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    page_memory.thread_conversation(session, UUID(int=1), Channel.gmail, "t-1")
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    for part in (
        "messages.company_id = %(company_id_1)s::UUID",
        "messages.channel = %(channel_1)s",
        "coalesce(messages.thread_ref, messages.provider_msg_id) = %(coalesce_1)s",
    ):
        assert part in sql

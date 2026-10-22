"""Migration 0012: agent_turns.timings jsonb (nullable) and the messages thread expression index."""

import pytest
from sqlalchemy import Engine, inspect

pytestmark = pytest.mark.integration


def test_0012_timings_column(migrated_engine: Engine) -> None:
    columns = {c["name"]: c for c in inspect(migrated_engine).get_columns("agent_turns")}
    assert columns["timings"]["nullable"] is True
    assert columns["timings"]["type"].__class__.__name__ == "JSONB"


def test_0012_thread_expression_index(migrated_engine: Engine) -> None:
    indexes = {i["name"]: i for i in inspect(migrated_engine).get_indexes("messages")}
    index = indexes["ix_messages_company_channel_thread"]
    assert index["unique"] is False
    assert index["column_names"][:2] == ["company_id", "channel"]
    assert [e.lower().replace(" ", "") for e in index["expressions"]] == [
        "company_id",
        "channel",
        "coalesce(thread_ref,provider_msg_id)",
    ]

"""Migration 0011: agent_turns.page_context jsonb, nullable."""

import pytest
from sqlalchemy import Engine, inspect

pytestmark = pytest.mark.integration


def test_0011_page_context_column(migrated_engine: Engine) -> None:
    columns = {c["name"]: c for c in inspect(migrated_engine).get_columns("agent_turns")}
    assert "page_context" in columns
    assert columns["page_context"]["nullable"] is True
    assert columns["page_context"]["type"].__class__.__name__ == "JSONB"

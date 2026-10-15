"""Migration 0009: dashboard channel, owner_feed, agent tables, companies.outbound_mode."""

import pytest
from sqlalchemy import Engine, inspect, text

pytestmark = pytest.mark.integration


def test_0009_objects(migrated_engine: Engine) -> None:
    insp = inspect(migrated_engine)
    assert {"owner_feed", "agent_conversations", "agent_turns"} <= set(insp.get_table_names())
    assert "outbound_mode" in {c["name"] for c in insp.get_columns("companies")}
    assert "updated_at" in {c["name"] for c in insp.get_columns("agent_turns")}
    with migrated_engine.connect() as c:
        assert c.execute(text("select outbound_mode from companies limit 1")).first() in (None, ("draft",))


def test_dashboard_channel_allowed(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as c:
        defs = c.execute(
            text("select pg_get_constraintdef(oid) from pg_constraint where conname='ck_messages_channel'")
        ).scalar_one()
        interactive = c.execute(
            text(
                "select pg_get_constraintdef(oid) from pg_constraint "
                "where conname='ck_owner_accounts_interactive_channel'"
            )
        ).scalar_one()
    assert "dashboard" in defs
    assert "dashboard" in interactive

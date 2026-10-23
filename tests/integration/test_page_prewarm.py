"""Page pre-warm against real Postgres: PUT /agent/page upserts one row per owner, a turn on the same page reuses the
stored facts without resolving, and another owner's/company's, stale or other-page state is never used.
Freshness against newer company data: test_page_prewarm_freshness.py."""

from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, inspect, select, update
from sqlalchemy.orm import Session

from app.contracts import PageContext
from app.db.models import AgentPageState, AgentTurn
from app.pipeline import concierge_page, page_facts, page_state
from tests.integration.page_prewarm_support import RESOLVER, World, make_world, page, post, put, states

pytestmark = pytest.mark.integration


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with make_world(migrated_engine, pg_url) as w:
        yield w


def test_two_puts_keep_one_row_with_the_latest_page_and_create_no_turn(world: World) -> None:
    put(world, page())
    (first,) = states(world, world.owner)
    put(world, page(view="tasks"))
    (second,) = states(world, world.owner)
    assert second.id == first.id
    assert second.page_key == page_state.page_key(PageContext.model_validate(page(view="tasks")))
    assert second.resolved_at >= first.resolved_at
    assert second.resolved["facts"].startswith("view: tasks")
    assert "warm snapshot" not in str(second.resolved)
    with Session(world.engine) as s:
        assert s.scalar(select(func.count()).select_from(AgentTurn).where(AgentTurn.company_id == world.company)) == 0


def test_a_turn_on_the_warmed_page_stores_the_facts_and_never_resolves(world: World) -> None:
    put(world, page())
    (state,) = states(world, world.owner)
    message_page = page(snapshot="the message's snapshot", filters={"status": "open"})
    with patch(RESOLVER, wraps=page_facts.resolve_page_facts) as spy:
        stored = post(world, message_page)
        assert stored is not None
        assert concierge_page.resolve_once(world.engine, world.company, stored) is None  # the run skips resolving
    spy.assert_not_called()
    assert stored["resolved"] == state.resolved
    assert stored["snapshot"] == "the message's snapshot"  # always from the message, never from the state row
    assert stored["filters"] == {"status": "open"}


def test_another_owners_or_companys_warm_state_is_never_used(world: World) -> None:
    put(world, page())
    for other in (world.sibling, world.foreign):
        world.as_(other)
        stored = post(world, page())
        assert stored is not None
        assert "resolved" not in stored, other
        assert states(world, other) == []
    world.as_(world.owner)
    stored = post(world, page())
    assert stored is not None
    assert "resolved" in stored


def test_a_put_from_another_company_never_moves_or_overwrites_the_row(world: World) -> None:
    put(world, page())
    (before,) = states(world, world.owner)
    other_page = PageContext.model_validate(page(view="tasks"))
    assert page_state.warm(world.engine, world.foreign.company_id, world.owner.owner_id, other_page) is False
    (after,) = states(world, world.owner)
    assert (after.company_id, after.page_key, after.resolved) == (world.company, before.page_key, before.resolved)


def test_stale_state_is_ignored_and_the_next_put_refreshes_it(world: World) -> None:
    put(world, page())
    with Session(world.engine) as s, s.begin():
        s.execute(
            update(AgentPageState)
            .where(AgentPageState.company_id == world.company, AgentPageState.owner_id == world.owner.owner_id)
            .values(resolved_at=func.now() - timedelta(seconds=121))
        )
    stored = post(world, page())
    assert stored is not None
    assert "resolved" not in stored
    put(world, page())
    stored = post(world, page())
    assert stored is not None
    assert "resolved" in stored


def test_a_different_page_is_not_reused(world: World) -> None:
    put(world, page())
    for changed in (page(view="tasks"), page(case_id=str(uuid4())), page(visible_ids=[])):
        stored = post(world, changed)
        assert stored is not None
        assert "resolved" not in stored


def test_foreign_ids_are_stored_as_dropped_kinds_only(world: World) -> None:
    world.as_(world.foreign)
    foreign_case = uuid4()
    put(world, page(case_id=str(foreign_case)))
    (state,) = states(world, world.foreign)
    assert "case" in state.resolved["dropped"]
    assert str(foreign_case) not in state.resolved["facts"]


def test_0015_table_columns_and_one_row_per_owner(migrated_engine: Engine) -> None:
    insp = inspect(migrated_engine)
    columns = {c["name"]: c for c in insp.get_columns("agent_page_state")}
    assert set(columns) == {
        "id",
        "company_id",
        "owner_id",
        "page_key",
        "resolved",
        "resolved_at",
        "created_at",
        "focus_trail",
    }  # focus_trail: migration 0019
    assert all(c["nullable"] is False for c in columns.values())
    assert columns["resolved"]["type"].__class__.__name__ == "JSONB"
    uniques = {u["name"]: u["column_names"] for u in insp.get_unique_constraints("agent_page_state")}
    assert uniques == {"uq_agent_page_state_owner_id": ["owner_id"]}
    indexes = {i["name"]: i["column_names"] for i in insp.get_indexes("agent_page_state")}
    assert indexes["ix_agent_page_state_company_id"] == ["company_id"]
    targets = {fk["referred_table"] for fk in insp.get_foreign_keys("agent_page_state")}
    assert targets == {"companies", "owner_accounts"}

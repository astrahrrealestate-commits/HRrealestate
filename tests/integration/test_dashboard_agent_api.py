"""Super Agent chat routes and turn events against real Postgres: commit-then-enqueue, scoping, length limit."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.core.settings import Settings
from app.db.enums import TurnStatus
from app.db.models import AgentConversation, AgentTurn, Company, OwnerAccount
from app.main import create_app
from app.pipeline import read_turns

pytestmark = pytest.mark.integration
H = {CSRF_HEADER: CSRF_VALUE}
URL = "/api/v1/agent/messages"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []
        self.down = False

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))
        if self.down:
            raise ConnectionError("dbos system db down")

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@dataclass
class World:
    client: TestClient
    wf: FakeClient
    engine: Engine
    company: UUID
    owner: UUID
    other_owner: UUID  # same company, different owner
    foreign_conversation: UUID  # company B
    sibling_conversation: UUID  # company A, other owner


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        ca, cb = Company(name="A"), Company(name="B")
        s.add_all([ca, cb])
        s.flush()
        owner = OwnerAccount(company_id=ca.id, display_name="H", whatsapp_e164="+31699999981", email="h@a.test")
        other = OwnerAccount(company_id=ca.id, display_name="P", whatsapp_e164="+31699999982", email="p@a.test")
        owner_b = OwnerAccount(company_id=cb.id, display_name="B", whatsapp_e164="+31699999983", email="b@b.test")
        s.add_all([owner, other, owner_b])
        s.flush()
        foreign = AgentConversation(company_id=cb.id, owner_id=owner_b.id)
        sibling = AgentConversation(company_id=ca.id, owner_id=other.id)
        s.add_all([foreign, sibling])
        s.commit()
        settings = Settings(
            database_url=pg_url,  # type: ignore[arg-type]
            env="test",
            dashboard_session_secret=SecretStr("x" * 32),
            _env_file=None,
        )
        principal = Principal(company_id=ca.id, owner_id=owner.id, email="h@a.test")
        wf = FakeClient()
        with TestClient(create_app(settings, engine=migrated_engine, workflow_client=wf)) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, wf, migrated_engine, ca.id, owner.id, other.id, foreign.id, sibling.id)
        ids = [ca.id, cb.id]
        for model in (AgentTurn, AgentConversation, OwnerAccount):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def _turns(w: World) -> int:
    with Session(w.engine) as s:
        return int(s.scalar(select(func.count()).select_from(AgentTurn).where(AgentTurn.company_id == w.company)) or 0)


def test_post_commits_a_pending_turn_then_enqueues_it(world: World) -> None:
    r = world.client.post(URL, json={"text": "tasks"}, headers=H)
    assert r.status_code == 202
    conv, turn = UUID(r.json()["conversation_id"]), UUID(r.json()["turn_id"])
    with Session(world.engine) as s:
        row = s.scalar(select(AgentTurn).where(AgentTurn.company_id == world.company, AgentTurn.id == turn))
        owner = s.scalar(select(AgentConversation.owner_id).where(AgentConversation.id == conv))
    assert row is not None
    assert (row.status, row.text, row.conversation_id) == (TurnStatus.pending, "tasks", conv)
    assert owner == world.owner
    assert world.wf.calls == [
        (
            {"queue_name": "concierge", "workflow_name": "concierge.turn", "workflow_id": f"concierge:{turn}"},
            (str(turn),),
        )
    ]
    again = world.client.post(URL, json={"text": "waiting", "conversation_id": str(conv)}, headers=H)
    assert again.json()["conversation_id"] == str(conv)


@pytest.mark.parametrize("which", ["foreign_conversation", "sibling_conversation"])
def test_other_conversations_are_404_and_create_nothing(world: World, which: str) -> None:
    conv = getattr(world, which)
    r = world.client.post(URL, json={"text": "tasks", "conversation_id": str(conv)}, headers=H)
    assert (r.status_code, r.json()) == (404, {"detail": "not found"})
    assert world.client.get(f"/api/v1/agent/conversations/{conv}").status_code == 404
    assert world.client.get(f"/api/v1/agent/conversations/{uuid4()}").json() == {"detail": "not found"}
    assert _turns(world) == 0
    assert world.wf.calls == []


def test_501_chars_is_422_and_writes_nothing(world: World) -> None:
    r = world.client.post(URL, json={"text": "a" * 501}, headers=H)
    assert r.status_code == 422
    assert _turns(world) == 0
    assert world.wf.calls == []


def test_conversation_returns_turns_oldest_first(world: World) -> None:
    first = world.client.post(URL, json={"text": "tasks"}, headers=H).json()
    conv = first["conversation_id"]
    world.client.post(URL, json={"text": "waiting", "conversation_id": conv}, headers=H)
    body = world.client.get(f"/api/v1/agent/conversations/{conv}").json()
    assert [t["text"] for t in body["turns"]] == ["tasks", "waiting"]
    assert body["turns"][0]["id"] == first["turn_id"]
    assert body["turns"][0]["status"] == "pending"
    assert body["turns"][0]["plan"] is None


def test_turn_events_are_owner_scoped_and_cursor_ordered(world: World) -> None:
    mine = UUID(world.client.post(URL, json={"text": "tasks"}, headers=H).json()["turn_id"])
    with Session(world.engine) as s, s.begin():
        s.add(AgentTurn(company_id=world.company, conversation_id=world.sibling_conversation, text="other owner"))
    start = (datetime.now(UTC) - timedelta(minutes=5), UUID(int=0))
    with Session(world.engine) as s:
        rows = read_turns.turns_changed_after(s, world.company, world.owner, start)
        assert [r.id for r in rows] == [mine]
        after = (rows[0].updated_at, rows[0].id)
        assert read_turns.turns_changed_after(s, world.company, world.owner, after) == []


def test_enqueue_failure_marks_the_committed_turn_failed(world: World) -> None:
    world.wf.down = True
    r = world.client.post(URL, json={"text": "tasks"}, headers=H)
    assert (r.status_code, r.json()) == (503, {"detail": "could not start the assistant; try again"})
    assert len(world.wf.calls) == 1
    with Session(world.engine) as s:
        rows = s.scalars(select(AgentTurn).where(AgentTurn.company_id == world.company)).all()
    assert [(t.status, t.error) for t in rows] == [(TurnStatus.failed, "ConnectionError")]
    assert rows[0].answer
    assert rows[0].updated_at > rows[0].created_at


@pytest.mark.parametrize("text", ["   ", "hi\x00there", "bell\x07"])
def test_blank_or_control_text_is_422_and_writes_nothing(world: World, text: str) -> None:
    assert world.client.post(URL, json={"text": text}, headers=H).status_code == 422
    assert _turns(world) == 0


def test_a_turn_failed_at_enqueue_is_never_run_later(world: World, test_settings: Settings) -> None:
    """The enqueue may have reached DBOS before raising: a late workflow run must not revive the failed turn."""
    from app.pipeline import concierge_turns

    world.wf.down = True
    world.client.post(URL, json={"text": "tasks"}, headers=H)
    with Session(world.engine) as s:
        turn = s.scalars(select(AgentTurn).where(AgentTurn.company_id == world.company)).one()
        before = (turn.status, turn.answer, turn.updated_at)
    concierge_turns.run_turn(world.engine, test_settings, turn.id)
    with Session(world.engine) as s:
        again = s.scalars(select(AgentTurn).where(AgentTurn.id == turn.id)).one()
    assert (again.status, again.answer, again.updated_at) == before

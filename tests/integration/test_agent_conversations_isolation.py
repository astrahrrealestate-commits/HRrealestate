"""Super Agent conversations belong to one owner: other companies' and other owners' threads do not exist for them."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.core.settings import Settings
from app.db.models import AgentConversation, AgentTurn, Company, OwnerAccount
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration


@dataclass
class Threads:
    client: TestClient
    engine: Engine
    mine: UUID
    colleague: UUID  # same company, another owner
    foreign: UUID  # another company


def _owner(s: Session, company_id: UUID, name: str) -> UUID:
    owner = OwnerAccount(
        company_id=company_id,
        display_name=name,
        whatsapp_e164=f"+3161{uuid4().int % 10**7:07d}",
        email=f"{name}@x.test",
    )
    s.add(owner)
    s.flush()
    return owner.id


def _thread(s: Session, company_id: UUID, owner_id: UUID, title: str) -> UUID:
    conv = AgentConversation(company_id=company_id, owner_id=owner_id, title=title)
    s.add(conv)
    s.flush()
    s.add(AgentTurn(company_id=company_id, conversation_id=conv.id, text=f"secret of {title}", answer=f"reply {title}"))
    return conv.id


@pytest.fixture
def threads(migrated_engine: Engine, pg_url: str) -> Iterator[Threads]:
    tag = uuid4().hex[:6]
    with Session(migrated_engine) as s:
        a, b = Company(name="Conv A"), Company(name="Conv B")
        s.add_all([a, b])
        s.flush()
        company_ids = (a.id, b.id)
        me, colleague = _owner(s, company_ids[0], f"me{tag}"), _owner(s, company_ids[0], f"col{tag}")
        stranger = _owner(s, company_ids[1], f"str{tag}")
        mine = _thread(s, company_ids[0], me, "Mine")
        theirs_same_company = _thread(s, company_ids[0], colleague, "Colleague")
        foreign = _thread(s, company_ids[1], stranger, "Foreign")
        s.commit()
    settings = Settings(database_url=pg_url, env="test", llm_model="fake", _env_file=None)  # type: ignore[call-arg]
    principal = Principal(company_id=company_ids[0], owner_id=me, email=f"me{tag}@x.test")
    app = as_owner(create_app(settings, engine=migrated_engine, workflow_client=MagicMock()), principal)
    with TestClient(app) as client:
        yield Threads(client, migrated_engine, mine, theirs_same_company, foreign)
    for company_id in company_ids:
        purge_company(migrated_engine, company_id)


def test_the_list_holds_only_the_owners_own_threads(threads: Threads) -> None:
    listed = threads.client.get("/api/agent/conversations").json()["conversations"]
    assert [c["id"] for c in listed] == [str(threads.mine)]


@pytest.mark.parametrize("which", ["colleague", "foreign"])
def test_someone_elses_thread_cannot_be_read_renamed_or_hidden(threads: Threads, which: str) -> None:
    target = getattr(threads, which)
    assert threads.client.get(f"/api/agent/conversations/{target}").status_code == 404
    patched = threads.client.patch(f"/api/agent/conversations/{target}", json={"title": "pwned", "hidden": True})
    assert patched.status_code == 404
    with Session(threads.engine) as s:
        conv = s.get(AgentConversation, target)
        assert conv is not None
        assert conv.title != "pwned"
        assert conv.hidden_at is None


def test_the_owners_own_thread_replays(threads: Threads) -> None:
    body = threads.client.get(f"/api/agent/conversations/{threads.mine}").json()
    assert body["id"] == str(threads.mine)
    assert any("secret of Mine" in t["text"] or "reply Mine" in t["text"] for t in body["turns"])


@pytest.mark.parametrize("which", ["colleague", "foreign"])
def test_asking_with_someone_elses_thread_id_starts_a_new_thread_and_leaves_theirs_alone(
    threads: Threads, which: str
) -> None:
    target = getattr(threads, which)
    with Session(threads.engine) as s:
        before = len(s.scalars(select(AgentTurn).where(AgentTurn.conversation_id == target)).all())
    r = threads.client.post("/api/agent/ask", json={"query": "hello", "conversation_id": str(target)})
    assert r.status_code == 200
    assert r.json()["conversation_id"] not in ("", str(target))
    with Session(threads.engine) as s:
        assert len(s.scalars(select(AgentTurn).where(AgentTurn.conversation_id == target)).all()) == before

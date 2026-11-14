"""Shared setup for the page pre-warm integration tests: two companies, three owners, the API with a fake
workflow client, and small PUT/POST/read helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.core.settings import Settings
from app.db.models import AgentPageState, AgentTurn, Company, OwnerAccount
from app.main import create_app
from tests.integration.conftest import purge_company

H = {CSRF_HEADER: CSRF_VALUE}
PAGE_URL = "/api/v1/agent/page"
MSG_URL = "/api/v1/agent/messages"
RESOLVER = "app.pipeline.concierge_page.resolve_page_facts"


class FakeClient:
    def enqueue(self, options: Any, *args: Any) -> Any:
        return None

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@dataclass
class World:
    client: TestClient
    engine: Engine
    settings: Settings
    company: UUID
    owner: Principal  # company A
    sibling: Principal  # company A, another owner
    foreign: Principal  # company B

    def as_(self, who: Principal) -> None:
        self.client.cookies.set(COOKIE, issue_session(self.settings, who, datetime.now(UTC)))


@contextmanager
def make_world(engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(engine, expire_on_commit=False) as s:
        ca, cb = Company(name="Warm A"), Company(name="Warm B")
        s.add_all([ca, cb])
        s.flush()
        rows = [
            OwnerAccount(company_id=ca.id, display_name="H", whatsapp_e164="+31699999971", email="h@warm-a.test"),
            OwnerAccount(company_id=ca.id, display_name="P", whatsapp_e164="+31699999972", email="p@warm-a.test"),
            OwnerAccount(company_id=cb.id, display_name="B", whatsapp_e164="+31699999973", email="b@warm-b.test"),
        ]
        s.add_all(rows)
        s.commit()
    owner, sibling, foreign = (Principal(company_id=r.company_id, owner_id=r.id, email=str(r.email)) for r in rows)
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    try:
        with TestClient(create_app(settings, engine=engine, workflow_client=FakeClient())) as client:
            w = World(client, engine, settings, ca.id, owner, sibling, foreign)
            w.as_(owner)
            yield w
    finally:
        purge_company(engine, ca.id)
        purge_company(engine, cb.id)


def page(**kw: Any) -> dict[str, Any]:
    return {"view": "inbox", "visible_ids": [str(UUID(int=7))], "snapshot": "warm snapshot", **kw}


def put(w: World, body: dict[str, Any]) -> None:
    assert w.client.put(PAGE_URL, json=body, headers=H).status_code == 204


def post(w: World, body: dict[str, Any]) -> dict[str, Any] | None:
    """POST a message with this page; the new turn's stored page_context."""
    r = w.client.post(MSG_URL, json={"text": "what is on this page?", "page": body}, headers=H)
    assert r.status_code == 202
    with Session(w.engine) as s:
        turn = s.get(AgentTurn, UUID(r.json()["turn_id"]))
        assert turn is not None
        return turn.page_context


def states(w: World, who: Principal) -> list[AgentPageState]:
    with Session(w.engine) as s:
        stmt = select(AgentPageState).where(
            AgentPageState.company_id == who.company_id, AgentPageState.owner_id == who.owner_id
        )
        return list(s.scalars(stmt))

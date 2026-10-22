from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.db.enums import TurnStatus
from app.db.models import AgentTurn
from app.main import create_app
from app.pipeline.owner_commands import TOO_LONG

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
H = {CSRF_HEADER: CSRF_VALUE}
URL = "/api/v1/agent/messages"
T0 = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@pytest.fixture
def wf() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(wf: FakeClient) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=wf)
    with patch("app.api.v1.agent.Session", MagicMock()), TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_post_creates_turn_then_enqueues_once(client: TestClient, wf: FakeClient) -> None:
    conv, turn = uuid4(), uuid4()
    with patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(conv, turn)) as create:
        r = client.post(URL, json={"text": "tasks"}, headers=H)
    assert r.status_code == 202
    assert r.json() == {"conversation_id": str(conv), "turn_id": str(turn)}
    assert create.call_args.args[1:] == (PRINCIPAL.company_id, PRINCIPAL.owner_id, None, "tasks")
    assert wf.calls == [
        (
            {"queue_name": "concierge", "workflow_name": "concierge.turn", "workflow_id": f"concierge:{turn}"},
            (str(turn),),
        )
    ]


def test_post_passes_conversation_id(client: TestClient, wf: FakeClient) -> None:
    conv = uuid4()
    with patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(conv, uuid4())) as create:
        assert client.post(URL, json={"text": "hi?", "conversation_id": str(conv)}, headers=H).status_code == 202
    assert create.call_args.args[3] == conv


def test_foreign_conversation_is_404_and_nothing_enqueued(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.agent.concierge_turns.create_turn", side_effect=NotFoundError("x")):
        r = client.post(URL, json={"text": "hi?", "conversation_id": str(uuid4())}, headers=H)
    assert (r.status_code, r.json()) == (404, {"detail": "not found"})
    assert wf.calls == []


def test_text_over_500_chars_is_422_too_long(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(uuid4(), uuid4())) as create:
        r = client.post(URL, json={"text": "a" * 501}, headers=H)
        ok = client.post(URL, json={"text": "a" * 500}, headers=H)
    assert r.status_code == 422
    assert TOO_LONG in r.text
    assert ok.status_code == 202
    assert create.call_count == 1
    assert len(wf.calls) == 1


def test_empty_text_is_422(client: TestClient) -> None:
    assert client.post(URL, json={"text": ""}, headers=H).status_code == 422


def test_post_requires_csrf_and_auth(client: TestClient, wf: FakeClient) -> None:
    assert client.post(URL, json={"text": "tasks"}).status_code == 403
    client.cookies.clear()
    assert client.post(URL, json={"text": "tasks"}, headers=H).status_code == 401
    assert client.get(f"/api/v1/agent/conversations/{uuid4()}").status_code == 401
    assert wf.calls == []


def _turn(text: str) -> AgentTurn:
    return AgentTurn(
        id=uuid4(), company_id=PRINCIPAL.company_id, conversation_id=uuid4(), text=text, plan={"in_scope": True},
        results=[{"intent": "answer", "summary": "<b>x</b>"}], answer="<b>x</b>", status=TurnStatus.done,
        created_at=T0, updated_at=T0,
    )  # fmt: skip


def test_conversation_lists_turns_scoped_to_principal(client: TestClient) -> None:
    conv = uuid4()
    turns = [_turn("first"), _turn("second")]
    with patch("app.api.v1.agent.read_turns.conversation_turns", return_value=turns) as read:
        r = client.get(f"/api/v1/agent/conversations/{conv}")
    assert r.status_code == 200
    assert read.call_args.args[1:] == (PRINCIPAL.company_id, PRINCIPAL.owner_id, conv)
    body = r.json()
    assert body["id"] == str(conv)
    assert [t["text"] for t in body["turns"]] == ["first", "second"]
    assert body["turns"][0]["answer"] == "<b>x</b>"  # returned as data, untouched
    assert body["turns"][0]["status"] == "done"


def test_foreign_conversation_get_is_404(client: TestClient) -> None:
    with patch("app.api.v1.agent.read_turns.conversation_turns", return_value=None):
        r = client.get(f"/api/v1/agent/conversations/{uuid4()}")
    assert (r.status_code, r.json()) == (404, {"detail": "not found"})


class BrokenClient(FakeClient):
    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))
        raise ConnectionError("dbos system db down")


def test_enqueue_failure_marks_turn_failed_and_answers_503() -> None:
    broken, engine, turn = BrokenClient(), MagicMock(), uuid4()
    app = create_app(SETTINGS, engine=engine, workflow_client=broken)
    with (
        patch("app.api.v1.agent.Session", MagicMock()),
        patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(uuid4(), turn)),
        patch("app.api.v1.agent.concierge_turns.fail_turn") as fail,
        TestClient(app) as c,
    ):
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        r = c.post(URL, json={"text": "tasks"}, headers=H)
    assert (r.status_code, r.json()) == (503, {"detail": "could not start the assistant; try again"})
    fail.assert_called_once_with(engine, turn, "ConnectionError")
    assert len(broken.calls) == 1  # no second enqueue


@pytest.mark.parametrize("text", ["   ", "\n\t ", "hi\x00there", "bell\x07", "esc\x1b[31m", "\x1f"])
def test_blank_or_control_text_is_422(client: TestClient, wf: FakeClient, text: str) -> None:
    with patch("app.api.v1.agent.concierge_turns.create_turn") as create:
        r = client.post(URL, json={"text": text}, headers=H)
    assert r.status_code == 422
    create.assert_not_called()
    assert wf.calls == []


def test_newlines_and_tabs_are_allowed(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(uuid4(), uuid4())) as create:
        r = client.post(URL, json={"text": "first line\n\tsecond line?"}, headers=H)
    assert r.status_code == 202
    assert create.call_args.args[4] == "first line\n\tsecond line?"


def test_crlf_text_is_allowed(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.agent.concierge_turns.create_turn", return_value=(uuid4(), uuid4())) as create:
        r = client.post(URL, json={"text": "one\r\ntwo?"}, headers=H)
    assert r.status_code == 202
    assert create.call_args.args[4] == "one\r\ntwo?"

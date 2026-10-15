from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.api.v1.ratelimit import RateLimiter
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
H = {CSRF_HEADER: CSRF_VALUE}
AGENT = "/api/v1/agent/messages"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeClient:
    def enqueue(self, options: Any, *args: Any) -> Any:
        return None


def principal() -> Principal:
    return Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")


def cookie(p: Principal) -> str:
    return issue_session(SETTINGS, p, datetime.now(UTC))


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(clock: Clock) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=FakeClient())
    app.state.rate_limiter = RateLimiter(clock=clock)
    with (
        patch("app.api.v1.agent.Session", MagicMock()),
        patch("app.api.v1.agent.concierge_turns.create_turn", side_effect=lambda *a: (uuid4(), uuid4())),
        TestClient(app) as c,
    ):
        app.state.rate_limiter = RateLimiter(clock=clock)  # lifespan does not own it; keep the injected clock
        yield c


def post_agent(c: TestClient, p: Principal) -> Any:
    return c.post(AGENT, json={"text": "tasks"}, headers=H, cookies={COOKIE: cookie(p)})


def test_31st_agent_message_is_429_with_retry_after(client: TestClient) -> None:
    p = principal()
    assert [post_agent(client, p).status_code for _ in range(30)] == [202] * 30
    r = post_agent(client, p)
    assert (r.status_code, r.json()) == (429, {"detail": "rate_limited"})
    assert int(r.headers["Retry-After"]) >= 1


def test_other_principal_is_unaffected(client: TestClient) -> None:
    a, b = principal(), principal()
    for _ in range(31):
        post_agent(client, a)
    assert post_agent(client, a).status_code == 429
    assert post_agent(client, b).status_code == 202


def test_refills_after_the_window(client: TestClient, clock: Clock) -> None:
    p = principal()
    for _ in range(31):
        post_agent(client, p)
    assert post_agent(client, p).status_code == 429
    clock.now += 60
    assert post_agent(client, p).status_code == 202


def test_partial_refill_allows_one_after_two_seconds(client: TestClient, clock: Clock) -> None:
    p = principal()
    for _ in range(30):
        post_agent(client, p)
    clock.now += 2  # 30/min = one token per 2 s
    assert post_agent(client, p).status_code == 202
    assert post_agent(client, p).status_code == 429


def test_unauthenticated_is_401_and_takes_no_token(client: TestClient) -> None:
    for _ in range(40):
        assert client.post(AGENT, json={"text": "x"}, headers=H).status_code == 401


def test_auth_session_is_limited_per_ip(client: TestClient) -> None:
    codes = [client.post("/api/v1/auth/session", json={"id_token": "bad"}, headers=H).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


def test_forwarded_header_ignored_by_default(client: TestClient) -> None:
    for i in range(11):
        r = client.post(
            "/api/v1/auth/session", json={"id_token": "bad"}, headers={**H, "X-Forwarded-For": f"10.0.0.{i}"}
        )
    assert r.status_code == 429


def test_gets_are_never_limited(client: TestClient) -> None:
    with patch("app.api.v1.agent.read_turns.conversation_turns", return_value=[]):
        for _ in range(200):
            r = client.get(f"/api/v1/agent/conversations/{uuid4()}", cookies={COOKIE: cookie(principal())})
            assert r.status_code == 200
    me = principal()
    assert all(client.get("/api/v1/me", cookies={COOKIE: cookie(me)}).status_code == 200 for _ in range(200))


def test_decision_writes_are_limited_at_120(client: TestClient) -> None:
    p = principal()
    with patch("app.api.v1.decisions._set_paused", return_value=True):
        codes = [
            client.post("/api/v1/company/pause", headers=H, cookies={COOKIE: cookie(p)}).status_code for _ in range(121)
        ]
    assert codes[:120] == [200] * 120
    assert codes[120] == 429


def test_limiter_unit_retry_after() -> None:
    lim = RateLimiter(clock=Clock())
    assert lim.check("g", "a", 1) is None
    assert lim.check("g", "a", 1) == 60


def test_eviction_keeps_the_most_recently_used() -> None:
    clock = Clock()
    lim = RateLimiter(clock=clock, max_buckets=4)
    for name in ("old1", "old2", "new1", "new2"):
        lim.check("g", name, 1)
        clock.now += 1
    lim.check("g", "extra", 1)  # table full and nothing idle: the older half goes
    assert lim.size() <= 4
    assert lim.check("g", "new2", 1) is not None  # still remembered (and still empty)
    assert lim.check("g", "old1", 1) is None  # forgotten: a fresh bucket


def test_idle_buckets_are_swept() -> None:
    clock = Clock()
    lim = RateLimiter(clock=clock, max_buckets=3)
    for name in ("a", "b", "c"):
        lim.check("g", name, 1)
    clock.now += 61
    lim.check("g", "d", 1)
    assert lim.size() == 1


def test_missing_client_shares_the_unknown_bucket(client: TestClient) -> None:
    from starlette.requests import Request

    from app.api.v1.ratelimit import client_ip

    scope = {"type": "http", "headers": [], "app": client.app}
    assert client_ip(Request(scope)) == "unknown"


@pytest.fixture
def trusting_client(clock: Clock) -> Iterator[TestClient]:
    app = create_app(SETTINGS.model_copy(update={"dashboard_trust_forwarded_for": True}), engine=MagicMock())
    app.state.rate_limiter = RateLimiter(clock=clock)
    with TestClient(app) as c:
        yield c


def test_forwarded_for_last_entry_is_used_when_trusted(trusting_client: TestClient) -> None:
    def login(forwarded: str) -> int:
        h = {**H, "X-Forwarded-For": forwarded}
        return trusting_client.post("/api/v1/auth/session", json={"id_token": "bad"}, headers=h).status_code

    assert [login("1.1.1.1, 9.9.9.9") for _ in range(10)] == [401] * 10
    assert login("2.2.2.2, 9.9.9.9") == 429  # same last entry: same bucket, a spoofed first entry changes nothing
    assert login("1.1.1.1, 8.8.8.8") == 401

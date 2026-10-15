from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import (
    AuthError,
    FakeIdTokenVerifier,
    Principal,
    issue_session,
    read_session,
)
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="harjot@example.test")
CSRF = {"X-EstateOS-Client": "dashboard"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    verifier = FakeIdTokenVerifier({"tok-harjot": "harjot@example.test"})
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), id_token_verifier=verifier)
    with patch("app.api.v1.auth.owner_by_email", return_value=PRINCIPAL), TestClient(app) as c:
        yield c


def test_valid_token_sets_cookie(client: TestClient) -> None:
    r = client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"})
    assert r.status_code == 200
    assert "eo_session" in r.cookies
    assert r.json() == {"email": PRINCIPAL.email, "company_id": str(PRINCIPAL.company_id)}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "secure" not in [part.strip() for part in cookie.split(";")]


def test_unknown_email_403() -> None:
    verifier = FakeIdTokenVerifier({"tok": "nobody@example.test"})
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), id_token_verifier=verifier)
    with patch("app.api.v1.auth.owner_by_email", return_value=None), TestClient(app) as c:
        assert c.post("/api/v1/auth/session", json={"id_token": "tok"}).status_code == 403


def test_bad_token_401(client: TestClient) -> None:
    assert client.post("/api/v1/auth/session", json={"id_token": "nope"}).status_code == 401


def test_me_after_login(client: TestClient) -> None:
    client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"})
    r = client.get("/api/v1/me")
    assert r.status_code == 200
    assert r.json()["email"] == PRINCIPAL.email


def test_me_requires_cookie(client: TestClient) -> None:
    assert client.get("/api/v1/me").status_code == 401


def test_tampered_cookie_401(client: TestClient) -> None:
    client.cookies.set("eo_session", "x.y.z")
    assert client.get("/api/v1/me").status_code == 401


def test_expired_session_401() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    token = issue_session(SETTINGS, PRINCIPAL, now)
    assert read_session(SETTINGS, token, now + timedelta(minutes=479)) == PRINCIPAL
    with pytest.raises(AuthError):
        read_session(SETTINGS, token, now + timedelta(minutes=481))


def test_write_without_csrf_header_403(client: TestClient) -> None:
    client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"})
    assert client.delete("/api/v1/auth/session").status_code == 403
    assert client.delete("/api/v1/auth/session", headers=CSRF).status_code == 204

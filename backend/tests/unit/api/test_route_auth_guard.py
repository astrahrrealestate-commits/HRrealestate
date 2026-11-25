"""Every HTTP route refuses an anonymous caller unless it is listed here as public, with the reason.

The scan walks the OpenAPI document of the real app, so a router added tomorrow is covered without touching this file:
a new route that answers an unauthenticated request fails the build until it is protected or deliberately allow-listed.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import Principal, issue_session
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=UUID(int=1), owner_id=UUID(int=2), email="harjot@example.test")
CSRF = {"X-EstateOS-Client": "dashboard"}
ID = "00000000-0000-0000-0000-000000000001"

# (method, path): why an anonymous caller may reach it. Webhooks are not listed: they answer 403 without a signature.
PUBLIC = {
    ("GET", "/health/live"): "liveness probe",
    ("GET", "/health/ready"): "readiness probe",
    ("GET", "/api/auth/login/config"): "the login page's own mode, before any session exists",
    ("GET", "/api/auth/login/google/url"): "starts the owner login",
    ("GET", "/api/auth/login/google/callback"): "finishes the owner login (the session starts here)",
    ("POST", "/api/auth/logout"): "clears the cookie; idempotent",
    ("GET", "/api/auth/me"): "answers authenticated=false itself",
}
ANONYMOUS_REFUSALS = {401, 403}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _routes(client: TestClient) -> list[tuple[str, str]]:
    paths = client.get("/openapi.json").json()["paths"]
    verbs = ("get", "post", "put", "patch", "delete")
    return [(verb.upper(), path) for path, ops in sorted(paths.items()) for verb in ops if verb in verbs]


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", ID, path)


def test_the_scan_sees_the_whole_api(client: TestClient) -> None:
    routes = _routes(client)
    assert len(routes) > 90
    for legacy in ("/api/agent/ask", "/api/inbox/approvals/{approval_id}/decide", "/api/properties", "/api/tenants"):
        assert any(path == legacy for _, path in routes), legacy


def test_every_route_refuses_an_anonymous_caller_unless_public(client: TestClient) -> None:
    open_routes = []
    for method, path in _routes(client):
        if (method, path) in PUBLIC:
            continue
        response = client.request(method, _fill(path), json={} if method != "GET" else None)
        if response.status_code not in ANONYMOUS_REFUSALS:
            open_routes.append(f"{response.status_code} {method} {path}")
    assert open_routes == [], "reachable without a session: " + ", ".join(open_routes)


def test_every_public_route_still_exists(client: TestClient) -> None:
    present = set(_routes(client))
    assert set(PUBLIC) <= present, "stale allow-list entries: " + str(sorted(set(PUBLIC) - present))


def _session_cookie() -> dict[str, str]:
    return {"eo_session": issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC))}


def test_a_valid_session_reaches_a_legacy_read_route(client: TestClient) -> None:
    with patch("app.api.v1.auth.owner_matches", return_value=True):
        response = client.get("/api/agent/conversations", cookies=_session_cookie())
    assert response.status_code != 401


def test_a_valid_session_without_the_client_header_cannot_change_state(client: TestClient) -> None:
    with patch("app.api.v1.auth.owner_matches", return_value=True):
        response = client.post(f"/api/inbox/approvals/{ID}/decide", json={}, cookies=_session_cookie())
    assert response.status_code == 403


def test_the_chat_send_routes_are_scanned_and_need_the_client_header(client: TestClient) -> None:
    present = set(_routes(client))
    assert {("POST", "/api/chats/{chat_key}/messages"), ("GET", "/api/chats/{chat_key}/suggestions")} <= present
    body = {"client_msg_id": ID, "text": "hi"}
    with patch("app.api.v1.auth.owner_matches", return_value=True):
        response = client.post("/api/chats/+31612345678/messages", json=body, cookies=_session_cookie())
    assert response.status_code == 403

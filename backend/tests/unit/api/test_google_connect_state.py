"""The Gmail connect flow is bound to the owner who started it by a signed, expiring `state`."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.auth import oauth_state
from app.api.auth.oauth_state import clean_return, issue_state, read_state
from app.api.v1.auth import AuthError, Principal, issue_session
from app.core.settings import Settings
from app.main import create_app
from tests.api_auth import OWNER, as_owner

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("s" * 32),
    frontend_base_url="https://dash.estateos.example",
    _env_file=None,
)
OTHER = Principal(company_id=UUID(int=7), owner_id=UUID(int=8), email="other@example.test")


def test_state_round_trips_the_owner_and_company() -> None:
    state = read_state(SETTINGS, issue_state(SETTINGS, OWNER, "/inbox"))
    assert (state.company_id, state.owner_id, state.return_to) == (OWNER.company_id, OWNER.owner_id, "/inbox")


def test_two_states_for_the_same_owner_differ() -> None:
    assert issue_state(SETTINGS, OWNER, "/") != issue_state(SETTINGS, OWNER, "/")


@pytest.mark.parametrize("bad", ["", "garbage", "a.b.c"])
def test_a_malformed_state_is_refused(bad: str) -> None:
    with pytest.raises(AuthError):
        read_state(SETTINGS, bad)


def test_a_tampered_state_is_refused() -> None:
    token = issue_state(SETTINGS, OWNER, "/")
    with pytest.raises(AuthError):
        read_state(SETTINGS, token[:-2] + ("AA" if not token.endswith("AA") else "BB"))


def test_a_state_signed_with_another_secret_is_refused() -> None:
    other = SETTINGS.model_copy(update={"dashboard_session_secret": SecretStr("o" * 32)})
    with pytest.raises(AuthError):
        read_state(SETTINGS, issue_state(other, OWNER, "/"))


def test_an_expired_state_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    token = issue_state(SETTINGS, OWNER, "/")
    monkeypatch.setattr(oauth_state, "MAX_AGE_S", -1)
    with pytest.raises(AuthError):
        read_state(SETTINGS, token)


def test_a_session_cookie_is_not_a_valid_state() -> None:
    cookie = issue_session(SETTINGS, OWNER, datetime.now(UTC))
    with pytest.raises(AuthError):
        read_state(SETTINGS, cookie)


@pytest.mark.parametrize(
    ("given", "kept"),
    [("/inbox", "/inbox"), ("/", "/"), ("//evil.test", "/"), ("https://evil.test", "/"), ("evil", "/"), ("", "/")],
)
def test_return_to_is_always_a_path_on_the_spa(given: str, kept: str) -> None:
    assert clean_return(given) == kept


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app, follow_redirects=False) as c:
        yield c


def test_the_callback_refuses_a_missing_or_forged_state_before_touching_google_or_the_database(
    client: TestClient,
) -> None:
    exchange = AsyncMock()
    with (
        patch("app.api.auth.google_routes.google_auth.exchange_code_for_tokens", exchange),
        patch("app.api.auth.google_routes.connect_mailbox") as connect,
    ):
        for query in (
            "?code=abc",
            "?code=abc&state=forged",
            f"?code=abc&state={issue_session(SETTINGS, OWNER, datetime.now(UTC))}",
        ):
            assert client.get(f"/api/auth/google/callback{query}").status_code == 403
    exchange.assert_not_awaited()
    connect.assert_not_called()


def test_the_callback_connects_only_the_company_and_owner_named_by_the_state(client: TestClient) -> None:
    state = issue_state(SETTINGS, OTHER, "/inbox")
    exchange = AsyncMock(return_value={"email": "Attacker@Mail.Test", "name": "A"})
    with (
        patch("app.api.auth.google_routes.google_auth.exchange_code_for_tokens", exchange),
        patch("app.api.auth.google_routes.connect_mailbox") as connect,
    ):
        response = client.get(f"/api/auth/google/callback?code=abc&state={state}")
    assert response.status_code == 307
    assert response.headers["location"].startswith(
        "https://dash.estateos.example/inbox?connections=open&google_connected="
    )
    _engine, verified, email, name = connect.call_args.args
    assert (verified.company_id, verified.owner_id, email, name) == (
        OTHER.company_id,
        OTHER.owner_id,
        "attacker@mail.test",
        "A",
    )


def test_a_denied_consent_redirects_back_without_connecting(client: TestClient) -> None:
    state = issue_state(SETTINGS, OWNER, "/")
    with patch("app.api.auth.google_routes.connect_mailbox") as connect:
        response = client.get(f"/api/auth/google/callback?error=access_denied&state={state}")
    assert "google_error=access_denied" in response.headers["location"]
    connect.assert_not_called()


def test_the_authorization_url_carries_a_state_signed_for_the_signed_in_owner() -> None:
    app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))
    with (
        patch(
            "app.api.auth.google_routes.google_auth.get_authorization_url", return_value="https://g.test/auth"
        ) as url,
        TestClient(app) as c,
    ):
        response = c.get("/api/auth/google/url?return_to=//evil.test")
    assert response.json() == {"url": "https://g.test/auth"}
    verified = read_state(SETTINGS, url.call_args.kwargs["state"])
    assert (verified.company_id, verified.owner_id, verified.return_to) == (OWNER.company_id, OWNER.owner_id, "/")
    assert parse_qs(urlparse(response.json()["url"]).query) == {}

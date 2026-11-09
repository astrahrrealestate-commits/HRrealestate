from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import GoogleAuthError, TransportError
from pydantic import SecretStr

from app.api.v1.auth import (
    AuthError,
    FakeIdTokenVerifier,
    GoogleIdTokenVerifier,
    Principal,
    dashboard_verifier,
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
_FAKE = FakeIdTokenVerifier({"tok-harjot": "harjot@example.test"})
CSRF = {"X-EstateOS-Client": "dashboard"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    verifier = FakeIdTokenVerifier({"tok-harjot": "harjot@example.test"})
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), id_token_verifier=verifier)
    with patch("app.api.v1.auth.owner_by_email", return_value=PRINCIPAL), TestClient(app) as c:
        yield c


def test_valid_token_sets_cookie(client: TestClient) -> None:
    r = client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"}, headers=CSRF)
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
        assert c.post("/api/v1/auth/session", json={"id_token": "tok"}, headers=CSRF).status_code == 403


def test_bad_token_401(client: TestClient) -> None:
    assert client.post("/api/v1/auth/session", json={"id_token": "nope"}, headers=CSRF).status_code == 401


def test_me_after_login(client: TestClient) -> None:
    client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"}, headers=CSRF)
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
    client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"}, headers=CSRF)
    assert client.delete("/api/v1/auth/session").status_code == 403
    assert client.delete("/api/v1/auth/session", headers=CSRF).status_code == 204


def test_login_without_csrf_header_403(client: TestClient) -> None:
    assert client.post("/api/v1/auth/session", json={"id_token": "tok-harjot"}).status_code == 403


def test_secure_cookie_in_prod_like_env() -> None:
    prod = SETTINGS.model_copy(update={"env": "prod"})
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), id_token_verifier=_FAKE)
    with patch("app.api.v1.auth.owner_by_email", return_value=PRINCIPAL), TestClient(app) as c:
        app.state.settings = prod  # create_app refuses fake providers in prod; swap after startup
        r = c.post("/api/v1/auth/session", json={"id_token": "tok-harjot"}, headers=CSRF)
        assert "secure" in [part.strip() for part in r.headers["set-cookie"].lower().split(";")]
        d = c.delete("/api/v1/auth/session", headers=CSRF)
        assert "secure" in [part.strip() for part in d.headers["set-cookie"].lower().split(";")]


def test_token_signed_with_other_secret_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    other = SETTINGS.model_copy(update={"dashboard_session_secret": SecretStr("y" * 32)})
    with pytest.raises(AuthError):
        read_session(SETTINGS, issue_session(other, PRINCIPAL, now), now)


def test_token_without_iat_rejected() -> None:
    from itsdangerous import URLSafeTimedSerializer

    payload = {"c": str(PRINCIPAL.company_id), "o": str(PRINCIPAL.owner_id), "e": PRINCIPAL.email}
    token = URLSafeTimedSerializer("x" * 32, salt="eo-session").dumps(payload)
    with pytest.raises(AuthError):
        read_session(SETTINGS, token, datetime.now(UTC))


def test_future_iat_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    token = issue_session(SETTINGS, PRINCIPAL, now + timedelta(seconds=120))
    with pytest.raises(AuthError):
        read_session(SETTINGS, token, now)
    token_ok = issue_session(SETTINGS, PRINCIPAL, now + timedelta(seconds=30))
    assert read_session(SETTINGS, token_ok, now) == PRINCIPAL


def test_dashboard_verifier_google_never_fake() -> None:
    google = SETTINGS.model_copy(update={"dashboard_auth_provider": "google", "google_oauth_client_id": "cid"})
    assert isinstance(dashboard_verifier(google), GoogleIdTokenVerifier)
    with pytest.raises(AuthError):
        dashboard_verifier(google.model_copy(update={"google_oauth_client_id": None}))


def test_dashboard_verifier_fake_default() -> None:
    assert dashboard_verifier(SETTINGS).verify("test-owner-token") == "owner@example.test"


def _google_login(side_effect: Exception | None = None, claims: dict[str, object] | None = None) -> int:
    verifier = GoogleIdTokenVerifier("cid")
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock(), id_token_verifier=verifier)
    target = "google.oauth2.id_token.verify_oauth2_token"
    with (
        patch(target, side_effect=side_effect, return_value=claims),
        patch("app.api.v1.auth.owner_by_email", return_value=PRINCIPAL),
        TestClient(app) as c,
    ):
        return c.post("/api/v1/auth/session", json={"id_token": "t"}, headers=CSRF).status_code


def test_google_value_error_401() -> None:
    assert _google_login(ValueError("bad")) == 401


def test_google_auth_error_401() -> None:
    assert _google_login(GoogleAuthError("bad")) == 401


def test_google_transport_error_503() -> None:
    assert _google_login(TransportError("down")) == 503


@pytest.mark.parametrize("verified", [False, "false", None])
def test_google_unverified_email_401(verified: object) -> None:
    assert _google_login(claims={"email": "a@b.test", "email_verified": verified}) == 401


def test_google_verified_email_ok() -> None:
    assert _google_login(claims={"email": "a@b.test", "email_verified": True}) == 200


def _dev(**kw: object) -> Settings:
    return SETTINGS.model_copy(update={"env": "dev", **kw})


def _anonymous_status(settings: Settings) -> int:
    app = create_app(settings, engine=MagicMock(), workflow_client=MagicMock())
    with patch("app.api.v1.auth.default_dev_principal", return_value=PRINCIPAL), TestClient(app) as c:
        return c.get("/api/v1/me").status_code


def test_dev_with_the_fake_provider_runs_without_a_login() -> None:
    assert _anonymous_status(_dev(dashboard_auth_provider="fake")) == 200


def test_dev_with_the_google_provider_does_not_fall_open() -> None:
    """A deployment configured for real logins but missing ENV=prod must still demand a session."""
    assert _anonymous_status(_dev(dashboard_auth_provider="google", google_oauth_client_id="c.test")) == 401


def test_test_and_prod_always_demand_a_session() -> None:
    assert _anonymous_status(SETTINGS) == 401

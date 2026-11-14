"""GET /api/auth/login/config: the login page's only way to know whether to call Google or offer the fake-auth
path, before any session exists. Unauthenticated on purpose — it must report only the mode, never a secret."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import Settings
from app.main import create_app


def _client(**overrides: object) -> TestClient:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost:1/db",
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
        **overrides,
    )
    app = create_app(settings, engine=MagicMock(), workflow_client=MagicMock())
    return TestClient(app)


def test_reports_fake_when_configured_fake() -> None:
    with _client(dashboard_auth_provider="fake") as client:
        assert client.get("/api/auth/login/config").json() == {"authProvider": "fake"}


def test_reports_google_when_configured_google() -> None:
    with _client(dashboard_auth_provider="google", google_oauth_client_id="x") as client:
        assert client.get("/api/auth/login/config").json() == {"authProvider": "google"}


def test_never_carries_the_google_client_id_or_secret() -> None:
    with _client(
        dashboard_auth_provider="google",
        google_oauth_client_id="real-client-id",
        google_oauth_client_secret=SecretStr("real-client-secret"),
    ) as client:
        body = client.get("/api/auth/login/config").json()
        assert "real-client-id" not in str(body)
        assert "real-client-secret" not in str(body)
        assert set(body) == {"authProvider"}

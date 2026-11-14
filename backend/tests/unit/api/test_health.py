from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

import app
from app.channels.registry import _media_credentials
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[call-arg]


def test_live_needs_no_database() -> None:
    engine = MagicMock()
    with TestClient(create_app(SETTINGS, engine=engine)) as client:
        r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": app.__version__}
    engine.connect.assert_not_called()


def test_ready_503_when_database_down() -> None:
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))
    with TestClient(create_app(SETTINGS, engine=engine)) as client:
        r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "checks": {"database": "error"}}


def test_ready_failure_leaks_no_details_in_body_or_logs() -> None:
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", {}, Exception("password=hunter2 host=db"))
    with TestClient(create_app(SETTINGS, engine=engine)) as client, capture_logs() as logs:
        r = client.get("/health/ready")
    assert r.status_code == 503
    assert "hunter2" not in r.text
    assert "host=" not in r.text
    assert "hunter2" not in repr(logs)
    assert [e["error_type"] for e in logs if e["event"] == "health.ready.database_error"] == ["OperationalError"]


def test_owned_engine_disposed_injected_engine_not(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = MagicMock()
    monkeypatch.setattr("app.main.make_engine", lambda url: owned)
    with TestClient(create_app(SETTINGS)):
        pass
    owned.dispose.assert_called_once()

    injected = MagicMock()
    with TestClient(create_app(SETTINGS, engine=injected)):
        pass
    injected.dispose.assert_not_called()


def test_factory_without_arguments_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.settings import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:1/db")
    monkeypatch.setattr("app.main.make_engine", lambda url: MagicMock())
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/health/live").status_code == 200
    finally:
        get_settings.cache_clear()


@pytest.fixture
def fresh_media_credentials() -> Iterator[None]:
    """Media credentials are read once per process: an earlier test's empty read must not leak in or out."""
    _media_credentials.cache_clear()
    yield
    _media_credentials.cache_clear()


@pytest.mark.usefixtures("fresh_media_credentials")
def test_prod_hides_docs_and_openapi(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WHATSAPP_MEDIA_TOKENS", '{"100000000000001": "k"}')
    creds = tmp_path / "gmail-read.json"
    creds.write_text("{}")
    prod = Settings(
        database_url="postgresql+psycopg://u:p@localhost:1/db",
        env="prod",
        whatsapp_provider="cloud_api",
        gmail_provider="google",
        storage_backend="s3",
        whatsapp_app_secret="s",
        whatsapp_verify_token="t",
        gmail_pubsub_audience="aud",
        whatsapp_api_base_url="https://waba-v2.360dialog.io",
        gmail_pubsub_service_account="push@p.iam.gserviceaccount.com",
        gmail_credentials_file=creds,
        gmail_pubsub_topic="projects/p/topics/gmail",
        s3_bucket="estateos-prod",
        llm_model="openai:gpt-4.1-mini",
        embedding_model="openai:text-embedding-3-small",
        openai_api_key="sk-test",
        drive_provider="google",
        drive_credentials_file=creds,
        price_source="competitors",
        brixx_provider="api",
        brixx_token="brixx-test",
        dashboard_auth_provider="google",
        dashboard_session_secret="x" * 32,
        google_oauth_client_id="c.apps.googleusercontent.com",
        google_chat_provider="google",
        google_chat_project_number="123456789",
        frontend_base_url="https://dash.estateos.example",
        google_login_redirect_uri="https://api.estateos.example/api/auth/login/google/callback",
        google_oauth_redirect_uri="https://api.estateos.example/api/auth/google/callback",
        _env_file=None,
    )  # type: ignore[call-arg]
    with TestClient(create_app(prod, engine=MagicMock())) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    with TestClient(create_app(SETTINGS, engine=MagicMock())) as client:
        assert client.get("/openapi.json").status_code == 200


def test_engine_has_connect_timeout() -> None:
    from unittest.mock import patch

    from app.db.session import CONNECT_TIMEOUT_SEC, POOL_TIMEOUT_SEC, make_engine

    with patch("app.db.session.create_engine") as create:
        make_engine("postgresql+psycopg://u:p@localhost:1/db")
    kwargs = create.call_args.kwargs
    assert kwargs["connect_args"]["connect_timeout"] == CONNECT_TIMEOUT_SEC
    assert kwargs["pool_timeout"] == POOL_TIMEOUT_SEC
    assert kwargs["pool_pre_ping"] is True


def test_unknown_route_404() -> None:
    with TestClient(create_app(SETTINGS, engine=MagicMock())) as client:
        assert client.get("/nope").status_code == 404


def test_factory_refuses_unsafe_prod_config() -> None:
    from app.core.errors import UnsafeConfigurationError

    unsafe = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="prod", _env_file=None)  # type: ignore[call-arg]
    with pytest.raises(UnsafeConfigurationError):
        create_app(unsafe, engine=MagicMock())

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

import app
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


def test_prod_hides_docs_and_openapi() -> None:
    prod = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="prod", _env_file=None)  # type: ignore[call-arg]
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

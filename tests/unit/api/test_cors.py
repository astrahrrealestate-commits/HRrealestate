"""Optional CORS allowlist (DASHBOARD_CORS_ORIGINS): off by default, exact origins only, never a wildcard."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app.core.settings import Settings
from app.main import create_app

SPA = "https://dashboard.example.test"
PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "x-estateos-client,content-type",
}


def _settings(origins: object = None) -> Settings:
    extra = {} if origins is None else {"dashboard_cors_origins": origins}
    return Settings(  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost:1/db",
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
        **extra,
    )


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, engine=MagicMock(), workflow_client=MagicMock()))


def test_no_allowlist_means_no_cors_headers() -> None:
    assert _settings().dashboard_cors_origins == []
    with _client(_settings()) as c:
        r = c.options("/api/v1/approvals/x/decide", headers={"Origin": SPA, **PREFLIGHT})
        assert "access-control-allow-origin" not in r.headers
        assert "access-control-allow-origin" not in c.get("/health/live", headers={"Origin": SPA}).headers


def test_an_allowlisted_origin_passes_the_preflight_with_credentials() -> None:
    with _client(_settings(SPA)) as c:
        r = c.options("/api/v1/approvals/x/decide", headers={"Origin": SPA, **PREFLIGHT})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == SPA
    assert r.headers["access-control-allow-credentials"] == "true"
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "x-estateos-client" in allowed
    assert "content-type" in allowed


def test_any_other_origin_is_not_allowed() -> None:
    with _client(_settings(SPA)) as c:
        r = c.options("/api/v1/approvals/x/decide", headers={"Origin": "https://evil.example.test", **PREFLIGHT})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_origins_parse_from_a_comma_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", f" {SPA}/ , https://b.example.test ")
    assert _settings().dashboard_cors_origins == [SPA, "https://b.example.test"]
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", "")
    assert _settings().dashboard_cors_origins == []


@pytest.mark.parametrize("origins", ["*", f"{SPA},*", ["https://*.example.test"]])
def test_a_wildcard_is_refused(origins: object) -> None:
    with pytest.raises(ValidationError, match="never"):
        _settings(origins)

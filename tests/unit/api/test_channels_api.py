"""WhatsApp setup status: needs a session, reports the configured provider, never a secret."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.core.settings import Settings
from app.main import create_app

URL = "/api/v1/channels/whatsapp/status"
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")


def _client(provider: str) -> Iterator[TestClient]:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        whatsapp_provider=provider,  # type: ignore[arg-type]
        whatsapp_app_secret=SecretStr("never-returned"),
        _env_file=None,
    )
    app = create_app(settings, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(settings, PRINCIPAL, datetime.now(UTC)))
        yield c


@pytest.fixture
def fake_client() -> Iterator[TestClient]:
    yield from _client("fake")


@pytest.fixture
def live_client() -> Iterator[TestClient]:
    yield from _client("360dialog")


def test_requires_a_session(fake_client: TestClient) -> None:
    fake_client.cookies.clear()
    assert fake_client.get(URL).status_code == 401


def test_the_fake_provider_is_not_configured(fake_client: TestClient) -> None:
    assert fake_client.get(URL).json() == {"configured": False, "provider": "fake"}


def test_a_real_provider_is_configured_and_no_secret_is_returned(live_client: TestClient) -> None:
    resp = live_client.get(URL)
    assert resp.json() == {"configured": True, "provider": "360dialog"}
    assert "never-returned" not in resp.text

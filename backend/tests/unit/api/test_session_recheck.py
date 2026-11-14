"""Sessions are re-checked per request: the owner row must still exist with the session's email (lookup mocked)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session, owner_matches
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="harjot@example.test")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_a_live_owner_keeps_the_session(client: TestClient) -> None:
    with patch("app.api.v1.auth.owner_matches", return_value=True) as lookup:
        assert client.get("/api/v1/me").status_code == 200
    assert lookup.call_args.args[1] == PRINCIPAL


def test_a_removed_owner_or_changed_email_ends_the_session(client: TestClient) -> None:
    with patch("app.api.v1.auth.owner_matches", return_value=False):
        assert client.get("/api/v1/me").status_code == 401


def test_a_bad_cookie_is_refused_before_any_lookup() -> None:
    with (
        TestClient(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())) as c,
        patch("app.api.v1.auth.owner_matches") as lookup,
    ):
        c.cookies.set(COOKIE, "forged")
        assert c.get("/api/v1/me").status_code == 401
    lookup.assert_not_called()


@pytest.mark.parametrize(
    ("stored", "ok"),
    [("harjot@example.test", True), ("Harjot@Example.TEST", True), ("new@example.test", False), (None, False)],
)
def test_owner_matches_compares_the_stored_email(stored: str | None, ok: bool) -> None:
    with patch("app.api.v1.auth.Session") as session:
        session.return_value.__enter__.return_value.scalar.return_value = stored
        assert owner_matches(MagicMock(), PRINCIPAL) is ok
    stmt = session.return_value.__enter__.return_value.scalar.call_args.args[0]
    compiled = str(stmt)
    assert "owner_accounts.id" in compiled
    assert "owner_accounts.company_id" in compiled

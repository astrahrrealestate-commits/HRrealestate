"""BRIXX status API without a database: session auth, company scoping from the principal, the interval setting."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts.brixx import BrixxStatus, BrixxTableStatus
from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    brixx_sync_interval_minutes=20,
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
URL = "/api/v1/brixx/status"
STATUS = BrixxStatus(
    last_run=None,
    tables=[
        BrixxTableStatus(
            name="PRG_RELATIE", row_count=7, last_success_at=None, lag_seconds=None, drifted=True, last_error=None
        )
    ],
    total_rows=7,
    stale=True,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with patch("app.api.v1.brixx.Session", MagicMock()), TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_status_requires_a_session(client: TestClient) -> None:
    client.cookies.clear()
    with patch("app.api.v1.brixx.load_status") as load:
        assert client.get(URL).status_code == 401
    load.assert_not_called()


def test_status_reads_the_principals_company_with_the_configured_interval(client: TestClient) -> None:
    with patch("app.api.v1.brixx.load_status", return_value=STATUS) as load:
        resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.json() == STATUS.model_dump(mode="json")
    args, kwargs = load.call_args
    assert args[1] == PRINCIPAL.company_id  # the session's company, never a query parameter
    assert kwargs["interval_minutes"] == 20
    assert kwargs["now"].utcoffset() is not None


def test_status_ignores_a_company_query_parameter(client: TestClient) -> None:
    with patch("app.api.v1.brixx.load_status", return_value=STATUS) as load:
        assert client.get(URL, params={"company_id": str(uuid4())}).status_code == 200
    assert load.call_args.args[1] == PRINCIPAL.company_id


def test_status_route_never_reaches_the_brixx_adapter() -> None:
    import app.api.v1.brixx as route

    source = Path(route.__file__).read_text(encoding="utf-8")
    assert "app.channels" not in source
    assert "brixx_api" not in source

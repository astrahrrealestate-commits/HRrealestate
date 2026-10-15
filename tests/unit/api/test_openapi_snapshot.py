import json
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from syrupy.assertion import SnapshotAssertion

from app.core.settings import Settings
from app.main import create_app

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app) as c:
        yield c


def test_v1_openapi_snapshot(client: TestClient, snapshot: SnapshotAssertion) -> None:
    spec = client.get("/openapi.json").json()
    v1 = {path: item for path, item in spec["paths"].items() if path.startswith("/api/v1")}
    assert json.dumps(v1, sort_keys=True, indent=2) == snapshot

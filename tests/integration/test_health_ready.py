import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.core.settings import Settings
from app.main import create_app

pytestmark = pytest.mark.integration


def test_ready_against_real_database(test_settings: Settings, migrated_engine: Engine) -> None:
    with TestClient(create_app(test_settings, engine=migrated_engine)) as client:
        r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}

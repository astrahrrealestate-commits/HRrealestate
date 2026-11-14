import json
from collections.abc import Iterator
from typing import Any
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


def _refs(node: object) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"].rsplit("/", 1)[-1]} if isinstance(node.get("$ref"), str) else set()
        return found.union(*(_refs(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_refs(v) for v in node))
    return set()


def _schemas_for(spec: dict[str, Any], paths: dict[str, Any]) -> dict[str, Any]:
    all_schemas = spec["components"]["schemas"]
    pending, seen = _refs(paths), set[str]()
    while pending:
        name = pending.pop()
        seen.add(name)
        pending |= _refs(all_schemas[name]) - seen
    return {name: all_schemas[name] for name in sorted(seen)}


def test_v1_openapi_snapshot(client: TestClient, snapshot: SnapshotAssertion) -> None:
    spec = client.get("/openapi.json").json()
    v1 = {path: item for path, item in spec["paths"].items() if path.startswith("/api/v1")}
    dump = {"paths": v1, "schemas": _schemas_for(spec, v1)}
    assert json.dumps(dump, sort_keys=True, indent=2) == snapshot

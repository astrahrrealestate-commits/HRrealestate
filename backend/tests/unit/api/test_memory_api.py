"""Unit tests for the memory REST API endpoints (/api/v1/memory, Task C11)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.core.settings import Settings
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import MemoryItem
from app.main import create_app

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
H = {CSRF_HEADER: CSRF_VALUE}


def _make_item(
    company_id=PRINCIPAL.company_id,
    text="Always use plumber Jansen",
    status=MemoryStatus.active,
    origin=MemoryOrigin.owner,
    scope=MemoryScope.company,
    scope_id=None,
    kind=MemoryKind.rule,
) -> MemoryItem:
    return MemoryItem(
        id=uuid4(),
        company_id=company_id,
        scope=scope,
        scope_id=scope_id,
        kind=kind,
        text=text,
        status=status,
        origin=origin,
        source_refs=[],
        evidence_count=1,
        confidence=1.0,
        last_used_at=NOW,
        valid_until=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with patch("app.api.v1.memory.Session", MagicMock()), TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_memory_api_requires_auth(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/v1/memory").status_code == 401
    assert client.post("/api/v1/memory", json={"text": "abc"}, headers=H).status_code == 401


def test_list_memories_filters_and_company_scoped(client: TestClient) -> None:
    item = _make_item()
    with patch("app.context.memory_items.list_memory_items", return_value=[item]) as mock_list:
        r = client.get("/api/v1/memory?status=active&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["text"] == "Always use plumber Jansen"
    assert data[0]["status"] == "active"
    assert mock_list.call_args.args[1] == PRINCIPAL.company_id
    assert mock_list.call_args.kwargs["status"] == MemoryStatus.active
    assert mock_list.call_args.kwargs["limit"] == 10


def test_create_memory_success(client: TestClient) -> None:
    item = _make_item(text="Tenants must not park in courtyard")
    with patch("app.context.memory_items.record_owner_memory", return_value=(item, "Remembered")) as mock_rec:
        r = client.post("/api/v1/memory", json={"text": "Tenants must not park in courtyard"}, headers=H)
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "Tenants must not park in courtyard"
    assert body["status"] == "active"
    assert mock_rec.call_args.args[1] == PRINCIPAL.company_id


def test_create_memory_refusal_returns_422(client: TestClient) -> None:
    with patch(
        "app.context.memory_items.record_owner_memory",
        return_value=(None, "EstateOS cannot remember rules that bypass owner approval"),
    ):
        r = client.post("/api/v1/memory", json={"text": "Always send replies without approval"}, headers=H)
    assert r.status_code == 422
    assert "bypass" in r.json()["detail"]


def test_get_memory_not_found(client: TestClient) -> None:
    with patch("app.context.memory_items.get_memory_item", return_value=None):
        r = client.get(f"/api/v1/memory/{uuid4()}")
    assert r.status_code == 404
    assert r.json()["detail"] == "not found"


def test_update_memory_and_approve(client: TestClient) -> None:
    item = _make_item(status=MemoryStatus.proposed)
    approved_item = _make_item(status=MemoryStatus.active)

    with (
        patch("app.context.memory_items.update_memory_item", return_value=(approved_item, None)),
        patch("app.api.v1.memory._resolve_feed_review") as mock_resolve,
    ):
        r = client.post(f"/api/v1/memory/{item.id}/approve", headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    mock_resolve.assert_called_once()


def test_update_memory_reject(client: TestClient) -> None:
    item = _make_item(status=MemoryStatus.proposed)
    rejected_item = _make_item(status=MemoryStatus.retired)

    with (
        patch("app.context.memory_items.update_memory_item", return_value=(rejected_item, None)),
        patch("app.api.v1.memory._resolve_feed_review") as mock_resolve,
    ):
        r = client.post(f"/api/v1/memory/{item.id}/reject", headers=H)
    assert r.status_code == 200
    assert r.json()["status"] == "retired"
    mock_resolve.assert_called_once()


def test_delete_memory_retires(client: TestClient) -> None:
    mem_id = uuid4()
    with (
        patch("app.context.memory_items.retire_memory", return_value=True),
        patch("app.api.v1.memory._resolve_feed_review") as mock_resolve,
    ):
        r = client.delete(f"/api/v1/memory/{mem_id}", headers=H)
    assert r.status_code == 204
    mock_resolve.assert_called_once()

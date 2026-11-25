from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.api.v1.schemas import ActivityItem, CompanyOut
from app.contracts import CaseState, Category, OutboundMode, Urgency
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.db.enums import TaskPriority, TaskStatus
from app.llm.agents.briefing import BriefingFacts
from app.main import create_app
from app.pipeline.read_cases import ActivityRow
from app.pipeline.work_repo import short_ref

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
T0 = datetime(2026, 1, 1, tzinfo=UTC)
SESSION = patch("app.api.v1.cases.Session", MagicMock()), patch("app.api.v1.work.Session", MagicMock())


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


@pytest.fixture(autouse=True)
def _sessions() -> Iterator[None]:
    with SESSION[0], SESSION[1]:
        yield


PATHS = ["/cases", f"/cases/{UUID(int=1)}", "/tasks", "/waits", "/briefing", "/activity", "/company"]


@pytest.mark.parametrize("path", PATHS)
def test_reads_require_auth(path: str) -> None:
    with TestClient(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())) as c:
        assert c.get(f"/api/v1{path}").status_code == 401


def test_case_missing_and_foreign_share_one_404(client: TestClient) -> None:
    with patch("app.api.v1.cases.case_bundle", side_effect=NotFoundError("case x not found")):
        a = client.get(f"/api/v1/cases/{uuid4()}")
        b = client.get(f"/api/v1/cases/{uuid4()}")
    assert a.status_code == b.status_code == 404
    assert a.json() == b.json()


def test_cases_passes_company_state_limit(client: TestClient) -> None:
    seen: dict[str, Any] = {}

    def fake(_s: Any, company_id: UUID, state: CaseState | None, limit: int) -> list[Any]:
        seen.update(company_id=company_id, state=state, limit=limit)
        return [
            SimpleNamespace(
                id=uuid4(), state=CaseState.open, category=Category.administration, urgency=Urgency.high, summary="s",
                opened_at=T0, resolved_at=None,
            )
        ]  # fmt: skip

    with patch("app.api.v1.cases.list_cases", fake):
        body = client.get("/api/v1/cases", params={"state": "open", "limit": 100}).json()
    assert seen == {"company_id": PRINCIPAL.company_id, "state": CaseState.open, "limit": 100}
    assert body[0]["urgency"] == "high"


@pytest.mark.parametrize("path", ["/cases", "/activity"])
def test_limit_bounds(client: TestClient, path: str) -> None:
    assert client.get(f"/api/v1{path}", params={"limit": 101}).status_code == 422
    assert client.get(f"/api/v1{path}", params={"limit": 0}).status_code == 422


def test_tasks_carry_short_ref(client: TestClient) -> None:
    tid = uuid4()
    task = SimpleNamespace(
        id=tid, title="Call plumber", assignee="owner", due_at=None, priority=TaskPriority.p1, status=TaskStatus.open,
        case_id=None,
    )  # fmt: skip
    with patch("app.api.v1.work.work_repo.open_tasks", return_value=[task]):
        body = client.get("/api/v1/tasks").json()
    assert body[0]["ref"] == short_ref(tid)
    assert "source" not in body[0]


def test_company_defaults_to_draft(client: TestClient) -> None:
    company = SimpleNamespace(name="A", paused=False, outbound_mode=OutboundMode.draft, timezone="Europe/Amsterdam")
    with patch("app.api.v1.work.get_company", return_value=company):
        body = client.get("/api/v1/company").json()
    assert body == {"name": "A", "paused": False, "outbound_mode": "draft", "timezone": "Europe/Amsterdam"}
    assert set(CompanyOut.model_fields) == set(body)


def test_briefing_uses_collector(client: TestClient) -> None:
    facts = BriefingFacts(kind="daily", day_label="Thu 15 Oct", urgent=["u"], stats={"x": 1})
    with patch("app.api.v1.work.briefing.collect", return_value=facts) as collect:
        body = client.get("/api/v1/briefing").json()
    assert collect.call_args.args[1:3] == (PRINCIPAL.company_id, "daily")
    assert body["urgent"] == ["u"]
    assert body["stats"] == {"x": 1}


def test_activity_serialises(client: TestClient) -> None:
    row = ActivityRow("send", uuid4(), T0, None, uuid4(), "whatsapp sent")
    with patch("app.api.v1.cases.activity", return_value=[row]) as act:
        body = client.get("/api/v1/activity", params={"limit": 5}).json()
    assert act.call_args.args[1:] == (PRINCIPAL.company_id, 5)
    assert body[0]["kind"] == "send"
    assert "case_id" in body[0]
    assert set(ActivityItem.model_fields) == set(body[0])


def test_latest_approval_is_highest_draft_version() -> None:
    from app.pipeline.read_cases import pick_latest

    action = uuid4()
    v1 = SimpleNamespace(action_id=action, draft_version=1)
    v2 = SimpleNamespace(action_id=action, draft_version=2)
    assert pick_latest([v1, v2])[action] == v2  # type: ignore[list-item]  # rows arrive sorted by version

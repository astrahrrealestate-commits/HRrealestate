from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.contracts import ActionType
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.main import create_app
from app.pipeline.approvals import Decision, NewRevision
from app.pipeline.dashboard_decisions import NotEditableError, SuspiciousNeedsConfirmError

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
ACTION = uuid4()
H = {CSRF_HEADER: CSRF_VALUE}


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@pytest.fixture
def wf() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(wf: FakeClient) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=wf)
    with (
        patch("app.api.v1.decisions.Session", MagicMock()),
        patch("app.api.v1.decisions._is_local", return_value=False),
        TestClient(app) as c,
    ):
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def _decide(c: TestClient, **body: Any) -> Any:
    return c.post(f"/api/v1/approvals/{uuid4()}/decide", json={"choice": "ok", **body}, headers=H)


def test_writes_require_csrf_and_auth(client: TestClient) -> None:
    assert client.post(f"/api/v1/approvals/{uuid4()}/decide", json={"choice": "ok"}).status_code == 403
    client.cookies.clear()
    assert _decide(client).status_code == 401


def test_execute_enqueues_once_with_deterministic_id(client: TestClient, wf: FakeClient) -> None:
    d = Decision("execute", ACTION, 2, 0)
    with patch("app.api.v1.decisions.dashboard_decisions.decide_approval", return_value=d):
        r = _decide(client)
    assert r.status_code == 200
    assert r.json()["kind"] == "execute"
    assert len(wf.calls) == 1
    options, args = wf.calls[0]
    assert options["workflow_id"] == f"exec:{ACTION}:2"
    assert options["workflow_name"] == "actions.execute_action"
    assert args == (str(ACTION), 2, False)


@pytest.mark.parametrize("kind", ["edit", "rejected", "stale"])
def test_other_kinds_never_enqueue(client: TestClient, wf: FakeClient, kind: str) -> None:
    with patch("app.api.v1.decisions.dashboard_decisions.decide_approval", return_value=Decision(kind, ACTION, 1)):  # type: ignore[arg-type]
        r = _decide(client)
    assert r.status_code == 200
    assert r.json()["stale"] is (kind == "stale")
    assert wf.calls == []


def test_suspicious_is_409(client: TestClient, wf: FakeClient) -> None:
    with patch(
        "app.api.v1.decisions.dashboard_decisions.decide_approval", side_effect=SuspiciousNeedsConfirmError("x")
    ):
        r = _decide(client)
    assert (r.status_code, r.json()["detail"]) == (409, "confirm_suspicious_required")
    assert wf.calls == []


def test_unknown_approval_404(client: TestClient) -> None:
    with patch("app.api.v1.decisions.dashboard_decisions.decide_approval", side_effect=NotFoundError("x")):
        assert _decide(client).status_code == 404


def test_edit_returns_revision_and_conflict(client: TestClient) -> None:
    rev = NewRevision(ACTION, 3, uuid4())
    url = f"/api/v1/approvals/{uuid4()}/edit"
    with patch("app.api.v1.decisions.dashboard_decisions.edit_approval", return_value=rev):
        r = client.post(url, json={"text": "hi"}, headers=H)
    assert r.json()["draft_version"] == 3
    with patch("app.api.v1.decisions.dashboard_decisions.edit_approval", side_effect=NotEditableError("x")):
        assert client.post(url, json={"text": "hi"}, headers=H).status_code == 409
    assert client.post(url, json={"text": ""}, headers=H).status_code == 422


def test_snooze_bad_duration_422(client: TestClient) -> None:
    assert client.post("/api/v1/tasks/abcd1234/snooze", json={"duration": "soon"}, headers=H).status_code == 422


def test_snooze_and_done_use_company_and_resolved_task(client: TestClient) -> None:
    tid = uuid4()
    with (
        patch("app.api.v1.decisions.work_repo.resolve_task", return_value=tid) as res,
        patch("app.api.v1.decisions.work_repo.snooze_task") as snooze,
        patch("app.api.v1.decisions.work_repo.complete_task") as done,
    ):
        assert client.post("/api/v1/tasks/abcd1234/snooze", json={"duration": "4h"}, headers=H).status_code == 204
        assert client.post("/api/v1/tasks/abcd1234/done", headers=H).status_code == 204
    assert res.call_args.args[1:] == (PRINCIPAL.company_id, "abcd1234")
    assert snooze.call_args.args[2] == tid
    assert done.call_args.args[2] == tid


def test_unknown_task_404(client: TestClient) -> None:
    with patch("app.api.v1.decisions.work_repo.resolve_task", side_effect=NotFoundError("x")):
        assert client.post("/api/v1/tasks/zzzz/done", headers=H).status_code == 404


def test_document_choice_validated(client: TestClient) -> None:
    r = client.post(f"/api/v1/documents/{uuid4()}/file", json={"choice": "bogus"}, headers=H)
    assert r.status_code == 422


def test_document_filing_enqueues_partitioned(client: TestClient, wf: FakeClient) -> None:
    att = uuid4()
    session = MagicMock()
    session.__enter__.return_value.scalar.return_value = att
    with patch("app.api.v1.decisions.Session", return_value=session):
        r = client.post(f"/api/v1/documents/{att}/file", json={"choice": "skip"}, headers=H)
    assert r.status_code == 202
    options, args = wf.calls[0]
    assert options["workflow_id"] == f"doc:{att}:owner:skip"
    assert options["queue_partition_key"] == str(PRINCIPAL.company_id)
    assert args == (str(PRINCIPAL.company_id), str(att), "skip")


def test_foreign_document_404(client: TestClient, wf: FakeClient) -> None:
    session = MagicMock()
    session.__enter__.return_value.scalar.return_value = None
    with patch("app.api.v1.decisions.Session", return_value=session):
        r = client.post(f"/api/v1/documents/{uuid4()}/file", json={"choice": "lease"}, headers=H)
    assert r.status_code == 404
    assert wf.calls == []


def test_resume_reenqueues_approved_unexecuted(client: TestClient, wf: FakeClient) -> None:
    a: UUID = uuid4()
    with (
        patch("app.api.v1.decisions._set_paused", return_value=True),
        patch("app.api.v1.decisions.approvals.approved_unexecuted", return_value=[(a, 4, ActionType.create_reminder)]),
    ):
        r = client.post("/api/v1/company/resume", headers=H)
    assert r.json() == {"paused": False}
    options, args = wf.calls[0]
    assert options["workflow_id"].startswith(f"exec:{a}:4:resume:")
    assert args == (str(a), 4, True)


def test_resume_when_not_paused_enqueues_nothing(client: TestClient, wf: FakeClient) -> None:
    with patch("app.api.v1.decisions._set_paused", return_value=False):
        assert client.post("/api/v1/company/resume", headers=H).status_code == 200
    assert wf.calls == []

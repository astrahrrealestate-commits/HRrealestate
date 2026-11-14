from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.contracts import ActionType
from app.core.settings import Settings
from app.db.enums import FeedKind
from app.main import create_app
from app.owner.cards import ApprovalCard
from app.pipeline.approvals import NewRevision
from app.pipeline.read_approvals import PendingApproval, ReviewDocument

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",  # type: ignore[arg-type]
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with patch("app.api.v1.reviews.Session", MagicMock()), TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_reads_require_auth(client: TestClient) -> None:
    client.cookies.clear()
    assert client.get("/api/v1/approvals").status_code == 401
    assert client.get("/api/v1/documents/review").status_code == 401


def test_approvals_listing_shape_and_company_scope(client: TestClient) -> None:
    row = PendingApproval(uuid4(), uuid4(), ActionType.reply_draft, uuid4(), "Sanne · other", ("a", "b"), 2, True, NOW)
    with patch("app.api.v1.reviews.pending_approvals", return_value=[row]) as read:
        r = client.get("/api/v1/approvals?limit=5")
    assert r.status_code == 200
    body = r.json()[0]
    assert (body["drafts"], body["draft_version"], body["suspicious"], body["action_type"]) == (
        ["a", "b"], 2, True, "reply_draft",
    )  # fmt: skip
    assert body["cursor"] == f"{NOW.isoformat()}|{row.id}"
    assert read.call_args.args[1] == PRINCIPAL.company_id
    assert read.call_args.args[3] == 5


def test_documents_review_listing(client: TestClient) -> None:
    row = ReviewDocument(uuid4(), uuid4(), "lease.pdf", "application/pdf", None, "lease", NOW)
    with patch("app.api.v1.reviews.review_documents", return_value=[row]):
        r = client.get("/api/v1/documents/review")
    assert r.json()[0]["suggested_type"] == "lease"
    assert r.json()[0]["case_id"] is None


@pytest.mark.parametrize("path", ["/api/v1/approvals", "/api/v1/documents/review"])
def test_bad_cursor_and_limit_are_422(client: TestClient, path: str) -> None:
    assert client.get(f"{path}?after=nope").status_code == 422
    assert client.get(f"{path}?limit=101").status_code == 422
    assert client.get(f"{path}?limit=0").status_code == 422


def test_edit_delivers_the_new_revision_card_idempotently(client: TestClient) -> None:
    new_approval = uuid4()
    card = ApprovalCard(new_approval, "Sanne · other", MagicMock(), "intent", "Reply", ("only draft",), None)
    with (
        patch("app.api.v1.decisions.Session", MagicMock()),
        patch(
            "app.api.v1.decisions.dashboard_decisions.edit_approval", return_value=NewRevision(uuid4(), 2, new_approval)
        ),
        patch("app.api.v1.decisions.load_card", return_value=card),
        patch("app.api.v1.decisions.feed.deliver") as deliver,
    ):
        r = client.post(f"/api/v1/approvals/{uuid4()}/edit", json={"text": "new"}, headers={CSRF_HEADER: CSRF_VALUE})
    assert r.status_code == 200
    keys = [c.args[2] for c in deliver.call_args_list]
    assert keys[0] == f"approval:{new_approval}:0"
    assert all(c.args[3] is FeedKind.approval and c.args[4] == new_approval for c in deliver.call_args_list)

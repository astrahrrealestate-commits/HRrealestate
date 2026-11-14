"""PUT /agent/page (page pre-warm): principal + CSRF, the same validated PageContext as POST, 204 with no body, never
a turn or a model call; resolver errors: non-transient -> 204 with nothing stored, transient -> 503."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError

from app.api.v1.auth import COOKIE, issue_session
from app.contracts import Channel, PageContext, PageView
from app.contracts.thread_key import encode_thread_key
from app.main import create_app
from app.pipeline.page_facts import PageFacts
from tests.unit.api.test_dashboard_agent import PRINCIPAL, SETTINGS, FakeClient, H

URL = "/api/v1/agent/page"
WARM = "app.api.v1.agent.page_state.warm"
CREATE = "app.api.v1.agent.concierge_turns.create_turn"


@pytest.fixture
def wf() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(wf: FakeClient) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=wf)
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def _put(client: TestClient, page: dict[str, Any], **kw: Any) -> tuple[Any, MagicMock]:
    with patch(WARM, return_value=True) as warm, patch(CREATE) as create:
        r = client.put(URL, json=page, headers=kw.get("headers", H))
    create.assert_not_called()
    return r, warm


def test_put_warms_the_principals_page_and_answers_204_without_a_body(client: TestClient, wf: FakeClient) -> None:
    case_id = uuid4()
    key = encode_thread_key(Channel.whatsapp, "+31612345678")
    r, warm = _put(client, {"view": "case", "case_id": str(case_id), "visible_ids": [key, "#A1B2C3"], "snapshot": "x"})
    assert (r.status_code, r.content) == (204, b"")
    _, company, owner, page = warm.call_args.args
    assert (company, owner) == (PRINCIPAL.company_id, PRINCIPAL.owner_id)
    assert isinstance(page, PageContext)
    assert (page.view, page.case_id, page.visible_ids) == (PageView.case, case_id, [key, "a1b2c3"])
    assert wf.calls == []  # never a turn, never a workflow


def test_a_resolver_bug_still_answers_204(client: TestClient) -> None:
    with patch(WARM, return_value=False):
        assert client.put(URL, json={"view": "inbox"}, headers=H).status_code == 204


def test_a_transient_error_is_503(client: TestClient) -> None:
    with patch(WARM, side_effect=OperationalError("select", {}, Exception("down"))):
        r = client.put(URL, json={"view": "inbox"}, headers=H)
    assert (r.status_code, r.json()) == (503, {"detail": "page facts unavailable; try again"})


def test_missing_csrf_header_is_403_and_warms_nothing(client: TestClient) -> None:
    r, warm = _put(client, {"view": "inbox"}, headers={})
    assert r.status_code == 403
    warm.assert_not_called()


def test_no_session_is_401_and_warms_nothing(client: TestClient) -> None:
    client.cookies.clear()
    r, warm = _put(client, {"view": "inbox"})
    assert r.status_code == 401
    warm.assert_not_called()


@pytest.mark.parametrize(
    "page",
    [
        {"view": "case", "thread_key": "not-a-key"},
        {"view": "case", "visible_ids": [str(uuid4()) for _ in range(51)]},
        {"view": "case", "snapshot": "x" * 6001},
        {"view": "case", "snapshot": "nul\x00byte"},
        {"view": "case", "filters": {f"k{i}": "v" for i in range(11)}},
        {"view": "case", "task_ref": "zzzzzz"},
        {"view": "nowhere"},
        {"case_id": str(uuid4())},
        {"view": "case", "unknown": 1},
    ],
)
def test_invalid_page_is_422_and_warms_nothing(client: TestClient, page: dict[str, Any]) -> None:
    r, warm = _put(client, page)
    assert r.status_code == 422
    warm.assert_not_called()


@pytest.mark.parametrize("view", [v.value for v in PageView])
def test_every_page_view_member_is_accepted(client: TestClient, view: str) -> None:
    """frontend/src/lib/api.ts's prewarmAgentPage must only ever send a real PageView member. One 422 here on a
    live dashboard, on every page but inbox, is exactly what shipped when it sent "cases"/"money"/"units"/"tenants"/
    "home" instead of this enum's real values (fixed to inbox/case/other)."""
    r, warm = _put(client, {"view": view})
    assert r.status_code == 204
    warm.assert_called_once()


@pytest.mark.parametrize("view", ["home", "cases", "money", "units", "tenants"])
def test_the_view_strings_the_dashboard_used_to_send_are_still_422(client: TestClient, view: str) -> None:
    r, warm = _put(client, {"view": view})
    assert r.status_code == 422
    warm.assert_not_called()


def test_foreign_ids_reach_the_resolver_and_are_stored_as_dropped_kinds_only(client: TestClient) -> None:
    """End to end through the real `page_state.warm` (session and resolver faked): the resolver drops the unknown
    ids; the stored value carries their kinds, never the ids."""
    foreign_case, foreign_approval = uuid4(), uuid4()
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    facts = PageFacts("case", dropped=("case", "approval"))
    with (
        patch("app.pipeline.page_state.Session", factory),
        patch("app.pipeline.concierge_page.resolve_page_facts", return_value=facts) as resolve,
    ):
        body = {"view": "case", "case_id": str(foreign_case), "approval_id": str(foreign_approval)}
        r = client.put(URL, json=body, headers=H)
    assert r.status_code == 204
    assert resolve.call_args.args[1] == PRINCIPAL.company_id
    params = session.execute.call_args.args[0].compile(dialect=postgresql.dialect()).params
    assert (params["company_id"], params["owner_id"]) == (PRINCIPAL.company_id, PRINCIPAL.owner_id)
    assert params["resolved"]["dropped"] == ["case", "approval"]
    assert str(foreign_case) not in str(params["resolved"])
    assert str(foreign_approval) not in str(params["resolved"])

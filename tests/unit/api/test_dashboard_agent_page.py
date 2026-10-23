"""`page` on POST /agent/messages: validated, handed to create_turn as a PageContext, rejected with 422 over limits."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.auth import COOKIE, issue_session
from app.contracts import Channel, PageContext, PageView
from app.contracts.thread_key import encode_thread_key
from app.main import create_app
from tests.unit.api.test_dashboard_agent import PRINCIPAL, SETTINGS, URL, FakeClient, H

CREATE = "app.api.v1.agent.concierge_turns.create_turn"


@pytest.fixture
def wf() -> FakeClient:
    return FakeClient()


@pytest.fixture
def client(wf: FakeClient) -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=wf)
    with patch("app.api.v1.agent.Session", MagicMock()), TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def _post(client: TestClient, page: dict[str, Any]) -> tuple[int, MagicMock]:
    with patch(CREATE, return_value=(uuid4(), uuid4())) as create:
        r = client.post(URL, json={"text": "summarise this", "page": page}, headers=H)
    return r.status_code, create


def test_page_is_validated_and_passed_to_create_turn(client: TestClient, wf: FakeClient) -> None:
    case_id = uuid4()
    key = encode_thread_key(Channel.whatsapp, "+31612345678")
    status, create = _post(
        client,
        {"view": "case", "case_id": str(case_id), "visible_ids": [key, "#A1B2C3"], "snapshot": "Sanne  ·  leak\n\n"},
    )
    assert status == 202
    page = create.call_args.kwargs["page"]
    assert isinstance(page, PageContext)
    assert (page.view, page.case_id, page.visible_ids, page.snapshot) == (
        PageView.case,
        case_id,
        [key, "a1b2c3"],
        "Sanne · leak",
    )
    assert len(wf.calls) == 1


def test_absent_page_is_none_and_the_call_is_unchanged(client: TestClient) -> None:
    with patch(CREATE, return_value=(uuid4(), uuid4())) as create:
        assert client.post(URL, json={"text": "tasks"}, headers=H).status_code == 202
    assert create.call_args.args[1:] == (PRINCIPAL.company_id, PRINCIPAL.owner_id, None, "tasks")
    assert create.call_args.kwargs == {"page": None}


@pytest.mark.parametrize(
    "page",
    [
        {"view": "case", "thread_key": "not-a-key"},
        {"view": "case", "visible_ids": [str(uuid4()) for _ in range(51)]},
        {"view": "case", "visible_ids": [str(uuid4()) for _ in range(1000)]},
        {"view": "case", "snapshot": "x" * 6001},
        {"view": "case", "snapshot": "nul\x00byte"},
        {"view": "case", "filters": {f"k{i}": "v" for i in range(11)}},
        {"view": "case", "task_ref": "zzzzzz"},
        {"view": "nowhere"},
        {"case_id": str(uuid4())},
    ],
)
def test_invalid_page_is_422_and_nothing_is_created(client: TestClient, wf: FakeClient, page: dict[str, Any]) -> None:
    status, create = _post(client, page)
    assert status == 422
    create.assert_not_called()
    assert wf.calls == []

"""The owner's writing persona: per company, editable over the API, used by the draft agent, stamped on drafts."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.context.persona import DEFAULT_NAME
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import ActionRow, Company, OwnerAccount
from app.main import create_app
from app.pipeline.propose import propose_for_message
from tests.integration.test_pipeline_propose import _setup

pytestmark = pytest.mark.integration
H = {CSRF_HEADER: CSRF_VALUE}
MARK = "PERSONA-MARKER-warm-and-short"


@pytest.fixture
def client(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[TestClient]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        owner = OwnerAccount(
            company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999994", email="h@p.test"
        )
        s.add(owner)
        s.commit()
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@p.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield c


def test_first_read_creates_the_mock_persona(client: TestClient) -> None:
    body = client.get("/api/v1/persona").json()
    assert (body["name"], body["version"], body["is_default"]) == (DEFAULT_NAME, 1, True)
    assert "Harjot" in body["content"]


def test_edit_bumps_version_and_marks_it_custom(client: TestClient) -> None:
    client.get("/api/v1/persona")
    sent = {"content": f"  {MARK}  ", "name": "Harjot v2", "filename": "harjot.md"}
    body = client.put("/api/v1/persona", json=sent, headers=H).json()
    assert (body["name"], body["version"], body["is_default"], body["content"]) == ("Harjot v2", 2, False, MARK)
    assert client.get("/api/v1/persona").json()["filename"] == "harjot.md"
    reset = client.post("/api/v1/persona/reset", headers=H).json()
    assert (reset["name"], reset["version"], reset["is_default"]) == (DEFAULT_NAME, 3, True)


@pytest.mark.parametrize("content", ["   ", "x" * 8001])
def test_blank_or_oversized_persona_is_rejected(client: TestClient, content: str) -> None:
    assert client.put("/api/v1/persona", json={"content": content}, headers=H).status_code == 422


def test_saving_needs_the_client_header(client: TestClient) -> None:
    assert client.put("/api/v1/persona", json={"content": "x"}).status_code == 403


def test_drafts_use_the_persona_and_record_which_one(
    client: TestClient,
    migrated_engine: Engine,
    committed_company: Company,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.put("/api/v1/persona", json={"content": MARK, "name": "Harjot v2"}, headers=H)
    seen: list[str] = []

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[-1]
        assert isinstance(request, ModelRequest)
        seen.append(str(request.parts[-1].content))  # type: ignore[union-attr]
        action = {
            "type": "reply_draft",
            "case_id": str(new_id()),
            "rationale": "r",
            "context_ref": [],
            "draft_version": 1,
            "payload": {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["A", "B"]},
        }
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"actions": [action]})])

    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: FunctionModel(reply))
    cid: UUID = committed_company.id
    propose_for_message(migrated_engine, test_settings, _setup(migrated_engine, cid))
    assert f"<persona>\n{MARK}\n</persona>" in seen[0]
    with Session(migrated_engine) as s:
        [row] = s.scalars(select(ActionRow).where(ActionRow.company_id == cid))
    assert (row.persona_name, row.persona_version) == ("Harjot v2", 2)
    threads = client.get("/api/inbox/threads").json()["threads"]
    personas = [t["draftPersona"] for t in threads if t.get("draftPersona")]
    assert personas == [{"actingAs": "Harjot", "name": "Harjot v2", "version": 2}]


def _drafted(
    client: TestClient, engine: Engine, cid: UUID, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> UUID:
    client.put("/api/v1/persona", json={"content": MARK, "name": "Harjot v2"}, headers=H)

    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        payload = {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["A", "B"]}
        action = {
            "type": "reply_draft", "case_id": str(new_id()), "rationale": "r", "context_ref": [],
            "draft_version": 1, "payload": payload,
        }  # fmt: skip
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"actions": [action]})])

    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: FunctionModel(reply))
    propose_for_message(engine, settings, _setup(engine, cid))
    with Session(engine) as s:
        return s.scalars(select(ActionRow.id).where(ActionRow.company_id == cid)).one()


def test_owner_edit_clears_the_persona_label_and_a_redraft_restamps_it(
    client: TestClient,
    migrated_engine: Engine,
    committed_company: Company,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.contracts import Urgency
    from app.llm.agents.proposer import Persona
    from app.pipeline.approvals import revise

    cid = committed_company.id
    action_id = _drafted(client, migrated_engine, cid, test_settings, monkeypatch)
    now = datetime.now(UTC)

    def revise_with(persona: Persona | None, editor: str) -> tuple[str | None, int | None]:
        with Session(migrated_engine) as s, s.begin():
            action = s.get(ActionRow, action_id)
            assert action is not None
            revise(s, cid, action, ["typed"], editor=editor, urgency=Urgency.normal, now=now, persona=persona)
            return action.persona_name, action.persona_version

    assert revise_with(Persona("Harjot v3", 3, "x"), "agent:t:0") == ("Harjot v3", 3)  # a redraft: the new version
    assert revise_with(None, "owner:m1") == (None, None)  # his own words: no persona claimed
    threads = client.get("/api/inbox/threads").json()["threads"]
    assert [t["draftPersona"] for t in threads if t.get("draftPersona")] == []


def test_first_edit_of_the_sample_is_renamed_and_nul_bytes_are_dropped(client: TestClient) -> None:
    body = client.put("/api/v1/persona", json={"content": "Hallo\x00 daar"}, headers=H).json()
    assert (body["name"], body["content"]) == ("Harjot (custom)", "Hallo daar")
    again = client.put("/api/v1/persona", json={"content": "Hoi"}, headers=H).json()
    assert again["name"] == "Harjot (custom)"  # a later edit keeps the name


def test_each_company_has_its_own_persona(client: TestClient, migrated_engine: Engine) -> None:
    from app.context.persona import load_persona

    client.put("/api/v1/persona", json={"content": MARK}, headers=H)
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other persona co")
        s.add(other)
        s.commit()
    try:
        assert MARK not in load_persona(migrated_engine, other.id).text
    finally:
        from tests.integration.conftest import purge_company

        purge_company(migrated_engine, other.id)


def test_only_tenant_facing_drafts_are_stamped() -> None:
    from app.context.persona import stamp_persona
    from app.contracts import NotifyOwnerPayload, ReplyDraftPayload
    from app.llm.agents.proposer import Persona

    persona = Persona("P", 4, "x")
    notice, reply = ActionRow(), ActionRow()
    stamp_persona(notice, NotifyOwnerPayload(kind="notify_owner", text="hi"), persona)
    stamp_persona(
        reply, ReplyDraftPayload(kind="reply_draft", channel="gmail", subject=None, body_variants=["a", "b"]), persona
    )
    assert (notice.persona_name, reply.persona_name, reply.persona_version) == (None, "P", 4)

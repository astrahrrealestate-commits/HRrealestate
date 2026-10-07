"""Integration tests: run_agent recording audit rows in model_calls."""

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.errors import AgentFailedError
from app.core.settings import Settings
from app.db.models import Company, ModelCall
from app.llm.agents.understanding import UNDERSTANDING
from app.llm.calls import CallContext, run_agent
from app.llm.prompts import load_prompt

pytestmark = pytest.mark.integration


def test_run_agent_records_model_call(
    migrated_engine: Engine,
    committed_company: Company,
    test_settings: Settings,
) -> None:
    ctx = CallContext(company_id=committed_company.id, purpose="triage_test")
    res = run_agent(migrated_engine, test_settings, UNDERSTANDING, "Help with leak", ctx)
    assert res.output is not None

    with Session(migrated_engine) as session:
        call = session.scalar(select(ModelCall).where(ModelCall.id == res.model_call_id))
        assert call is not None
        assert call.purpose == "triage_test"
        assert call.prompt_name == "understanding"
        assert call.prompt_version == "v1"
        assert call.prompt_sha256 == load_prompt(UNDERSTANDING.prompt).sha256
        assert call.model == "fake"
        assert call.error is None
        assert call.output is not None


def test_run_agent_records_failure_on_bad_output(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A fake model that returns bad tool arguments causing a validation failure
    def broken_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool_name = info.output_tools[0].name if info.output_tools else "output"
        return ModelResponse(parts=[ToolCallPart(tool_name, {"not_valid": 123})])

    broken_model = FunctionModel(broken_fn)
    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _name: broken_model)

    ctx = CallContext(company_id=committed_company.id, purpose="failure_test")
    with pytest.raises(AgentFailedError):
        run_agent(migrated_engine, test_settings, UNDERSTANDING, "Crash me", ctx)

    with Session(migrated_engine) as session:
        calls = session.scalars(
            select(ModelCall).where(ModelCall.company_id == committed_company.id, ModelCall.purpose == "failure_test")
        ).all()
        assert len(calls) == 1
        assert calls[0].error is not None
        assert calls[0].output is None

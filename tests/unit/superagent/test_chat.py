"""The Super Agent's direct-answer call: one Pydantic AI text call on the configured model (Gemini by default)."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.core.errors import BudgetExceededError
from app.core.settings import Settings
from app.superagent import chat


def _settings(model: str = "google-gla:gemini-2.5-flash") -> Settings:
    return Settings(llm_model=model)  # type: ignore[call-arg]


def _echo(seen: dict[str, Any]) -> FunctionModel:
    def reply(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["messages"] = messages
        seen["instructions"] = info.instructions
        return ModelResponse(parts=[TextPart("Morning, Harjot.")])

    return FunctionModel(reply)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    rows: list[Any] = []
    monkeypatch.setattr(chat, "check_budget", lambda *a, **k: None)
    monkeypatch.setattr(chat, "_record", lambda _engine, row: rows.append(row))
    return rows


def test_chat_answer_uses_the_configured_model_and_records_one_call(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(chat, "build_model", lambda _settings, _name: _echo(seen))
    company_id = uuid4()
    out = chat.chat_answer(MagicMock(), _settings(), company_id, "SYSTEM TEXT", ["User: hi", "Assistant: hello"], "Hi")
    assert out == "Morning, Harjot."
    assert "SYSTEM TEXT" in str(seen["instructions"])
    texts = [
        p.content
        for m in seen["messages"]
        if isinstance(m, ModelRequest)
        for p in m.parts
        if isinstance(p, UserPromptPart)
    ]
    assert texts == ["hi", "Hi"]  # earlier turn, then the new message
    assert len(recorded) == 1
    assert recorded[0].company_id == company_id
    assert recorded[0].purpose == "concierge"
    assert recorded[0].prompt_name == chat.AGENT_NAME
    assert recorded[0].model == "google-gla:gemini-2.5-flash"


def test_chat_answer_is_skipped_on_the_offline_fake_model(recorded: list[Any]) -> None:
    assert chat.chat_answer(MagicMock(), _settings("fake"), uuid4(), "s", [], "Hi") is None
    assert recorded == []


def test_chat_answer_returns_none_when_the_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    def spent(*_a: Any, **_k: Any) -> None:
        raise BudgetExceededError("day")

    monkeypatch.setattr(chat, "check_budget", spent)
    assert chat.chat_answer(MagicMock(), _settings(), uuid4(), "s", [], "Hi") is None
    assert recorded == []


def test_chat_answer_returns_none_and_records_the_error_when_the_model_fails(
    monkeypatch: pytest.MonkeyPatch, recorded: list[Any]
) -> None:
    def boom(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider down")

    monkeypatch.setattr(chat, "build_model", lambda _settings, _name: FunctionModel(boom))
    assert chat.chat_answer(MagicMock(), _settings(), uuid4(), "s", [], "Hi") is None
    assert len(recorded) == 1
    assert "provider down" in (recorded[0].error or "")


def test_history_lines_become_alternating_model_messages() -> None:
    msgs = chat.history_messages(["User: a", "Assistant: b", "stray line"])
    assert [type(m) for m in msgs] == [ModelRequest, ModelResponse, ModelResponse]


def test_token_budget_leaves_room_for_a_conversational_reply() -> None:
    assert chat.CHAT_MAX_TOKENS >= 600

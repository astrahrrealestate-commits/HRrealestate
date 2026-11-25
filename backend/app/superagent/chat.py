"""The Super Agent's direct answer: one Pydantic AI text call on the configured model (`settings.llm_model`, Gemini
by default), with the bounded system prompt of `app.context.super_agent_prompt`.

Every call writes one `model_calls` row, success or failure (ADR 0002). Any failure, a spent budget or the offline
`fake` model returns None so the caller falls back to its deterministic answer; this module never raises for a
provider problem. The system prompt is code, not a published prompt file, so the row's prompt version is `code` and
its hash is the sha256 of the exact system text sent.
"""

import hashlib
import time
from collections.abc import Sequence
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.settings import ModelSettings
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceededError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.budget import CONCIERGE_PURPOSE, check_budget
from app.llm.runtime import build_model, describe_model_error

log = get_logger(__name__)

AGENT_NAME = "super_agent_chat"
PROMPT_VERSION = "code"
CHAT_MAX_TOKENS = 1500  # Gemini thinking tokens count against the cap; the prompt, not the cap, keeps answers short
MAX_HISTORY_LINES = 24  # 12 exchanges
TURN_CHARS = 1200


def record_call(engine: Engine, row: ModelCall) -> None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(row)


def new_call(settings: Settings, company_id: UUID, agent: str, system_prompt: str, query: str) -> ModelCall:
    """The audit row of one call of a code-defined prompt (`prompt_version` `code`, hash of the exact system text)."""
    return ModelCall(
        id=new_id(), company_id=company_id, purpose=CONCIERGE_PURPOSE, prompt_name=agent,
        prompt_version=PROMPT_VERSION, prompt_sha256=hashlib.sha256(system_prompt.encode()).hexdigest(),
        model=settings.llm_model, input={"prompt": query},
    )  # fmt: skip


def history_messages(lines: Sequence[str]) -> list[ModelMessage]:
    """`User:` (dashboard chat) and `owner:` (stored turns) lines are owner turns; every other line is an assistant
    turn. Each is clipped to `TURN_CHARS`."""
    out: list[ModelMessage] = []
    for line in lines[-MAX_HISTORY_LINES:]:
        speaker, found, text = line.partition(":")
        text = text.strip()[:TURN_CHARS]
        if found and speaker.strip().lower() in ("user", "owner"):
            out.append(ModelRequest(parts=[UserPromptPart(text)]))
        elif found and speaker.strip().lower() == "assistant":
            out.append(ModelResponse(parts=[TextPart(text)]))
        else:
            out.append(ModelResponse(parts=[TextPart(line.strip()[:TURN_CHARS])]))
    return out


def chat_answer(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    system_prompt: str,
    history: Sequence[str],
    query: str,
) -> str | None:
    if settings.llm_model == "fake":
        return None
    try:
        check_budget(engine, settings, company_id, CONCIERGE_PURPOSE)
    except BudgetExceededError:
        return None
    row = new_call(settings, company_id, AGENT_NAME, system_prompt, query)
    started = time.perf_counter()
    try:
        result = Agent(build_model(settings, AGENT_NAME), instructions=system_prompt).run_sync(
            query,
            message_history=history_messages(history),
            model_settings=ModelSettings(timeout=settings.llm_timeout_sec, max_tokens=CHAT_MAX_TOKENS),
        )
    except Exception as exc:  # a provider problem degrades to the caller's fallback, never to a 500
        row.latency_ms = int((time.perf_counter() - started) * 1000)
        row.error = f"{type(exc).__name__}: {exc}"[:2000]
        record_call(engine, row)
        log.warning("superagent.chat_failed", company_id=str(company_id), error=describe_model_error(exc))
        return None
    row.latency_ms = int((time.perf_counter() - started) * 1000)
    row.output = {"chars": len(result.output)}
    row.tokens_in, row.tokens_out = result.usage.input_tokens, result.usage.output_tokens
    record_call(engine, row)
    return result.output.strip() or None

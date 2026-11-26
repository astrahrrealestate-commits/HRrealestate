"""Agent invocation wrapper: prompt loading, model execution, and model_calls recording (ADR 0002).

Every call writes one `model_calls` row, success or failure. Invalid output (after Pydantic AI's own retries) and
non-retryable provider errors raise `AgentFailedError`; transient provider errors (429/5xx, network, timeout)
propagate unchanged so the calling DBOS step retries them.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import FallbackExceptionGroup, ModelHTTPError
from pydantic_ai.messages import UserContent
from pydantic_ai.settings import ModelSettings, ThinkingLevel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import PromptRef
from app.core.errors import AgentFailedError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.budget import check_budget
from app.llm.prompts import LoadedPrompt, load_prompt
from app.llm.runtime import build_model, describe_model_error, model_name_for, output_for
from app.llm.tiers import tier_of

AGENT_RETRIES = 2  # re-asks on contract validation failure, inside one run


@dataclass(frozen=True)
class CallContext:
    company_id: UUID
    purpose: str
    prefix_hash: str | None = None
    message_ids: tuple[UUID, ...] = ()  # messages whose text is in the prompt, so erasure can find the call


@dataclass(frozen=True)
class CallResult[T]:
    output: T
    model_call_id: UUID


@dataclass(frozen=True)
class AgentSpec[T]:
    name: str
    prompt: PromptRef
    output_type: type[T]
    finalize: Callable[[T, LoadedPrompt], T]
    redact_output: bool = False  # the output is document text stored elsewhere: `model_calls` keeps only its size
    redact_input: bool = False  # the prompt is other people's mail: `model_calls` keeps only its size (erasure)
    gemini_prompted: bool = (
        False  # schema too nested for Gemini's tool mode: prompt for JSON instead (runtime.output_for)
    )
    # Reasoning effort. Gemini 2.5 thinks by default and bills those hidden tokens as output (a 500-token draft took
    # 4,750 tokens and 26 s), so agents on the inbox's critical path turn it down. None keeps the provider default.
    thinking: ThinkingLevel | None = None


def is_transient(exc: BaseException) -> bool:
    """Provider hiccups worth a step retry: rate limits, 5xx, network errors and timeouts."""
    if isinstance(exc, FallbackExceptionGroup):  # every provider failed: worth a retry if any of them was transient
        return any(is_transient(inner) for inner in exc.exceptions)
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in (408, 409, 429) or exc.status_code >= 500
    return isinstance(exc, httpx.TransportError | TimeoutError | ConnectionError)


def _cost(result: Any) -> Decimal | None:
    try:
        return Decimal(str(result.response.cost().total_price))
    except Exception:  # fake/unknown models have no price; cost is audit data, never a failure
        return None


def _record(engine: Engine, row: ModelCall) -> None:
    with Session(engine, expire_on_commit=False) as session, session.begin():
        session.add(row)


def describe_prompt(prompt: str | Sequence[UserContent]) -> str:
    """What `model_calls.input` records: the text, with each binary part (an image) as a size placeholder."""
    if isinstance(prompt, str):
        return prompt
    return "\n".join(
        part
        if isinstance(part, str)
        else f"[{getattr(part, 'media_type', 'binary')}: {len(getattr(part, 'data', b''))} bytes]"
        for part in prompt
    )


def _row(
    spec: AgentSpec[Any],
    loaded: LoadedPrompt,
    settings: Settings,
    ctx: CallContext,
    prompt: str | Sequence[UserContent],
) -> ModelCall:
    text = describe_prompt(prompt)
    stored: dict[str, Any] = {"redacted": True, "chars": len(text)} if spec.redact_input else {"prompt": text}
    return ModelCall(
        id=new_id(), company_id=ctx.company_id, purpose=ctx.purpose, prompt_name=spec.prompt.name,
        prompt_version=spec.prompt.version, prompt_sha256=loaded.sha256, model=model_name_for(settings, spec.name),
        input=stored, prefix_hash=ctx.prefix_hash, message_ids=list(ctx.message_ids),
    )  # fmt: skip


def model_settings(settings: Settings, spec: AgentSpec[Any]) -> ModelSettings:
    """Fast agents keep their own reasoning level and the global caps; quality agents (app.llm.tiers) think `high`
    with the longer timeout and token cap, since Gemini counts thinking tokens as output."""
    if tier_of(spec.name) == "quality":
        return ModelSettings(
            timeout=settings.llm_quality_timeout_sec,
            max_tokens=settings.llm_quality_max_output_tokens,
            thinking="high",
        )
    chosen = ModelSettings(timeout=settings.llm_timeout_sec, max_tokens=settings.llm_max_output_tokens)
    if spec.thinking is not None:
        chosen["thinking"] = spec.thinking
    return chosen


def run_agent[T: BaseModel](
    engine: Engine, settings: Settings, spec: AgentSpec[T], user_prompt: str | Sequence[UserContent], ctx: CallContext
) -> CallResult[T]:
    loaded = load_prompt(spec.prompt)
    check_budget(engine, settings, ctx.company_id, ctx.purpose)
    agent = Agent(
        build_model(settings, spec.name),
        output_type=output_for(settings, spec.output_type, gemini_prompted=spec.gemini_prompted),
        instructions=loaded.text,
        retries=AGENT_RETRIES,
    )
    row = _row(spec, loaded, settings, ctx, user_prompt)
    started = time.perf_counter()
    try:
        result = agent.run_sync(
            user_prompt,
            model_settings=model_settings(settings, spec),
        )
        output = spec.finalize(result.output, loaded)
    except Exception as exc:
        row.latency_ms, row.error = int((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"[:2000]
        _record(engine, row)
        if is_transient(exc):
            raise
        raise AgentFailedError(f"{spec.name}: {describe_model_error(exc)}") from exc
    usage = result.usage
    row.latency_ms = int((time.perf_counter() - started) * 1000)
    dumped = output.model_dump(mode="json")
    row.output = {"redacted": True, "chars": len(str(dumped))} if spec.redact_output else dumped
    row.cost_usd = _cost(result)
    row.tokens_in, row.tokens_out = usage.input_tokens, usage.output_tokens
    row.tokens_cached = getattr(usage, "cache_read_tokens", None)
    if (configured := model_name_for(settings, spec.name)) != "fake":  # provider's resolved name, for audit and drift
        row.model = getattr(result.response, "model_name", None) or configured
    _record(engine, row)
    return CallResult(output=output, model_call_id=row.id)

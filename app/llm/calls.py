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
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import UserContent
from pydantic_ai.settings import ModelSettings
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import PromptRef
from app.core.errors import AgentFailedError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.budget import check_budget
from app.llm.prompts import LoadedPrompt, load_prompt
from app.llm.runtime import build_model

AGENT_RETRIES = 2  # re-asks on contract validation failure, inside one run


@dataclass(frozen=True)
class CallContext:
    company_id: UUID
    purpose: str


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


def is_transient(exc: BaseException) -> bool:
    """Provider hiccups worth a step retry: rate limits, 5xx, network errors and timeouts."""
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
    return ModelCall(
        id=new_id(), company_id=ctx.company_id, purpose=ctx.purpose, prompt_name=spec.prompt.name,
        prompt_version=spec.prompt.version, prompt_sha256=loaded.sha256, model=settings.llm_model,
        input={"prompt": describe_prompt(prompt)},
    )  # fmt: skip


def run_agent[T: BaseModel](
    engine: Engine, settings: Settings, spec: AgentSpec[T], user_prompt: str | Sequence[UserContent], ctx: CallContext
) -> CallResult[T]:
    loaded = load_prompt(spec.prompt)
    check_budget(engine, settings, ctx.company_id, ctx.purpose)
    agent = Agent(
        build_model(settings, spec.name), output_type=spec.output_type, instructions=loaded.text, retries=AGENT_RETRIES
    )
    row = _row(spec, loaded, settings, ctx, user_prompt)
    started = time.perf_counter()
    try:
        result = agent.run_sync(
            user_prompt,
            model_settings=ModelSettings(timeout=settings.llm_timeout_sec, max_tokens=settings.llm_max_output_tokens),
        )
        output = spec.finalize(result.output, loaded)
    except Exception as exc:
        row.latency_ms, row.error = int((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"[:2000]
        _record(engine, row)
        if is_transient(exc):
            raise
        raise AgentFailedError(f"{spec.name}: {type(exc).__name__}") from exc
    usage = result.usage
    row.latency_ms = int((time.perf_counter() - started) * 1000)
    dumped = output.model_dump(mode="json")
    row.output = {"redacted": True, "chars": len(str(dumped))} if spec.redact_output else dumped
    row.cost_usd = _cost(result)
    row.tokens_in, row.tokens_out = usage.input_tokens, usage.output_tokens
    if settings.llm_model != "fake":  # the provider's resolved name (e.g. a dated snapshot), for audit and drift
        row.model = getattr(result.response, "model_name", None) or settings.llm_model
    _record(engine, row)
    return CallResult(output=output, model_call_id=row.id)

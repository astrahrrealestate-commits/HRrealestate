"""Agent invocation wrapper: prompt loading, model execution, and model_calls recording."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import Agent
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import PromptRef
from app.core.errors import AgentFailedError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.prompts import LoadedPrompt, load_prompt
from app.llm.runtime import build_model


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


def run_agent[T](
    engine: Engine,
    settings: Settings,
    spec: AgentSpec[T],
    user_prompt: str,
    ctx: CallContext,
) -> CallResult[T]:
    loaded = load_prompt(spec.prompt)
    model = build_model(settings, spec.name)
    agent = Agent(
        model,
        output_type=spec.output_type,
        instructions=loaded.text,
        retries=2,
    )

    call_id = new_id()
    start_time = time.perf_counter()
    tokens_in: int | None = None
    tokens_out: int | None = None

    try:
        result = agent.run_sync(user_prompt)
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        output_data = spec.finalize(result.output, loaded)

        if hasattr(result, "usage") and result.usage is not None:
            tokens_in = getattr(result.usage, "input_tokens", None)
            tokens_out = getattr(result.usage, "output_tokens", None)

        dumped_output = (
            output_data.model_dump(mode="json") if hasattr(output_data, "model_dump") else dict(output_data)  # type: ignore[call-overload]
        )

        with Session(engine) as session, session.begin():
            row = ModelCall(
                id=call_id,
                company_id=ctx.company_id,
                purpose=ctx.purpose,
                prompt_name=spec.prompt.name,
                prompt_version=spec.prompt.version,
                prompt_sha256=loaded.sha256,
                model=settings.llm_model,
                input={"prompt": user_prompt},
                output=dumped_output,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=None,
                latency_ms=latency_ms,
                langfuse_trace_id=None,
                error=None,
            )
            session.add(row)

        return CallResult(output=output_data, model_call_id=call_id)

    except Exception as exc:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        err_msg = str(exc)
        with Session(engine) as session, session.begin():
            row = ModelCall(
                id=call_id,
                company_id=ctx.company_id,
                purpose=ctx.purpose,
                prompt_name=spec.prompt.name,
                prompt_version=spec.prompt.version,
                prompt_sha256=loaded.sha256,
                model=settings.llm_model,
                input={"prompt": user_prompt},
                output=None,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=None,
                latency_ms=latency_ms,
                langfuse_trace_id=None,
                error=err_msg,
            )
            session.add(row)
        raise AgentFailedError(err_msg) from exc

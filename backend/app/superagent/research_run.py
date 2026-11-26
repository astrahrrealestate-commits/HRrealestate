"""How one research run is started, bounded and given up (M13 T15): the conversation as a data block, the run on a
worker thread with a request cap, and a run past its deadline cancelled or stopped, its usage recorded when it ends."""

import contextvars
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage, UsageLimits
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.context.compiler import SUMMARY_PREFIX
from app.contracts.sourced_answer import SourcedAnswer
from app.db.models import ModelCall
from app.llm.render import data_block
from app.superagent.research_base import MAX_TOOL_CALLS, SuperAgentDeps

MAX_TOKENS = 4000  # Gemini counts thinking tokens against the cap
HISTORY_LINES = 24  # 12 exchanges
HISTORY_LINE_CHARS = 1220
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="research")


def _conversation(history: Sequence[str]) -> str:
    """The conversation so far as data: earlier answers may quote mail or pages, so they are never replayed as turns."""
    lines = [" ".join(line.split())[:HISTORY_LINE_CHARS] for line in history if line.strip()]
    summary = [line for line in lines if line.startswith(SUMMARY_PREFIX)]
    turns = [line for line in lines if not line.startswith(SUMMARY_PREFIX)][-HISTORY_LINES:]
    return "\n" + data_block("conversation", "\n".join([*summary, *turns])) if summary or turns else ""


def _start(
    deadline: float, agent: Agent[SuperAgentDeps, SourcedAnswer], query: str, deps: SuperAgentDeps
) -> "Future[AgentRunResult[SourcedAnswer]]":
    """The run on a worker thread, so a hung provider cannot hold the owner's request past the deadline."""
    settings = ModelSettings(timeout=min(deps.settings.llm_timeout_sec, deadline), max_tokens=MAX_TOKENS)
    limits = UsageLimits(request_limit=MAX_TOOL_CALLS + 3, tool_calls_limit=MAX_TOOL_CALLS + 5)
    context = contextvars.copy_context()  # keeps the trace of the turn
    return _POOL.submit(
        context.run, lambda: agent.run_sync(query, deps=deps, usage_limits=limits, model_settings=settings)
    )


def record_late_usage(engine: Engine, call_id: UUID, usage: RunUsage) -> None:
    """The tokens of a run that finished after its owner was told it ran out of time (the budget must count them)."""
    with Session(engine) as session, session.begin():
        row = session.scalar(select(ModelCall).where(ModelCall.id == call_id))
        if row is not None:
            row.tokens_in, row.tokens_out = usage.input_tokens, usage.output_tokens


def _given_up(engine: Engine, call_id: UUID, run: "Future[AgentRunResult[SourcedAnswer]]") -> None:
    """A run past its deadline: never started if it can still be cancelled; else it stops at its next lookup and its
    usage is recorded once it ends."""
    if run.cancel():
        return

    def done(finished: "Future[AgentRunResult[SourcedAnswer]]") -> None:
        if not finished.cancelled() and finished.exception() is None:
            record_late_usage(engine, call_id, finished.result().usage)

    run.add_done_callback(done)

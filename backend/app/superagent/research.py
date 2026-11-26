"""The Super Agent's read-only research loop (spec 2026-11-06 §4; sources and open tools: M13 T11, T15).

One Pydantic AI agent with read-only tools: search and open messages, documents, people and the database, at most
`MAX_TOOL_CALLS` lookups per question. `company_id` and the engine come from the server-built deps, never from model
arguments; the model opens and cites by the short references a tool handed it in this run (`sources`), never by id; and
every tool result goes back inside an escaped `<data>` block (CLAUDE.md invariants 4 and 6). Nothing here can send,
approve or write: actions stay `ConciergePlan` steps that the executor validates.

A run has a deadline: lookups stop after a share of it, and past it the owner is told what was checked. `run_research`
returns None for the offline `fake` model, a spent budget or a failure; the caller then falls back to the plain direct
answer. Every run writes one `model_calls` row.
"""

import contextvars
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as DeadlineError
from uuid import UUID

from pydantic_ai import Agent, RunContext
from pydantic_ai.run import AgentRunResult
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts.sourced_answer import SourcedAnswer
from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.budget import CONCIERGE_PURPOSE, check_budget
from app.llm.embeddings import TextEmbedder
from app.llm.render import data_block
from app.llm.runtime import build_model, describe_model_error
from app.superagent.chat import history_messages, new_call, record_call
from app.superagent.lookups import database as _database
from app.superagent.lookups import documents as _documents
from app.superagent.lookups import messages as _messages
from app.superagent.lookups import messages_filtered as _messages_filtered
from app.superagent.lookups import plural as _plural
from app.superagent.lookups import web as _web
from app.superagent.open_tools import named_people, open_document, open_message, open_person, open_thread
from app.superagent.research_base import (
    AGENT_NAME,
    LOOKUP_FAILED,
    MAX_TOOL_CALLS,
    NO_MORE_LOOKUPS,
    NO_RESULTS,
    NOT_AVAILABLE,
    OUT_OF_TIME,
    RESEARCH_RULES,
    TOOL_SHARE,
    ResearchResult,
    SuperAgentDeps,
)
from app.superagent.sources import screen

__all__ = ["MAX_TOOL_CALLS", "ResearchResult", "SuperAgentDeps", "run_research"]

log = get_logger(__name__)
MAX_TOKENS = 4000  # Gemini counts thinking tokens against the cap
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="research")


def _safely(
    lookup: Callable[[SuperAgentDeps, str], tuple[str, int]], deps: SuperAgentDeps, arg: str
) -> tuple[str, int]:
    """A failing lookup is a result the model can explain, not a reason to abort the run and lose the other steps."""
    try:
        return lookup(deps, arg)
    except Exception as exc:
        log.warning("superagent.lookup_failed", company_id=str(deps.company_id), error=type(exc).__name__)
        return LOOKUP_FAILED, 0


def _as_data(text: str) -> str:
    return data_block("data", text or NO_RESULTS)


def _open(
    deps: SuperAgentDeps, label: str, row_id: UUID | None, opener: Callable[[Session, UUID, UUID], str | None]
) -> str:
    """Open a row by an id the server resolved from a reference; an unknown reference costs a call and opens nothing."""
    if not deps.take_call():
        return NO_MORE_LOOKUPS

    def lookup(d: SuperAgentDeps, _arg: str) -> tuple[str, int]:
        if row_id is None:
            return NOT_AVAILABLE, 0
        with Session(d.engine) as session:
            text = opener(session, d.company_id, row_id)
        return (text, 1) if text is not None else (NOT_AVAILABLE, 0)

    text, opened = _safely(lookup, deps, "")
    if opened:
        deps.steps.append(f"Opened {label}")
    return _as_data(text)


def _build_agent(settings: Settings, system_prompt: str) -> Agent[SuperAgentDeps, SourcedAnswer]:
    agent: Agent[SuperAgentDeps, SourcedAnswer] = Agent(
        build_model(settings, AGENT_NAME),
        deps_type=SuperAgentDeps,
        output_type=SourcedAnswer,
        instructions=system_prompt + RESEARCH_RULES,
    )
    _add_search_tools(agent)
    _add_open_tools(agent)
    return agent


def _add_search_tools(agent: Agent[SuperAgentDeps, SourcedAnswer]) -> None:
    @agent.tool
    def query_database(ctx: RunContext[SuperAgentDeps], question: str) -> str:
        """Ask a factual or analytical question about units, leases, rent ledger, profitability, vendor rates,
        people, cases, tasks, visits, waits, documents, approvals, or send stats in plain language."""
        if not ctx.deps.take_call():
            return NO_MORE_LOOKUPS
        text, rows = _safely(_database, ctx.deps, question)
        step = f"Checked the database ({_plural(rows, 'row', 'rows')})"
        ctx.deps.steps.append(step)
        ref = ctx.deps.sources.add("data", f"query {len(ctx.deps.steps)}", step)
        return _as_data(f"[{ref}] {text}")

    @agent.tool
    def search_communications(
        ctx: RunContext[SuperAgentDeps],
        query: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        channel: str | None = None,
    ) -> str:
        """Search tenant/contractor WhatsApp and email messages by keywords and/or date range (YYYY-MM-DD)."""
        if not ctx.deps.take_call():
            return NO_MORE_LOOKUPS
        if date_from is None and date_to is None and channel is None:
            text, hits = _safely(_messages, ctx.deps, query)
        else:
            text, hits = _safely(
                lambda deps, q: _messages_filtered(deps, q, date_from=date_from, date_to=date_to, channel=channel),
                ctx.deps,
                query,
            )
        ctx.deps.steps.append(f"Searched messages ({_plural(hits, 'match', 'matches')})")
        return _as_data(text)

    @agent.tool
    def search_web(ctx: RunContext[SuperAgentDeps], query: str) -> str:
        """Search public web pages (prices, rules, laws, products) for what our own data cannot answer."""
        if not ctx.deps.take_call():
            return NO_MORE_LOOKUPS
        text, pages = _safely(_web, ctx.deps, query)
        ctx.deps.steps.append(f"Searched the web ({_plural(pages, 'page', 'pages')})")
        return _as_data(text)

    @agent.tool
    def search_documents(ctx: RunContext[SuperAgentDeps], query: str) -> str:
        """Search stored leases, contracts and files for words or topics."""
        if not ctx.deps.take_call():
            return NO_MORE_LOOKUPS
        text, hits = _safely(_documents, ctx.deps, query)
        ctx.deps.steps.append(f"Searched documents ({_plural(hits, 'match', 'matches')})")
        return _as_data(text)


def _add_open_tools(agent: Agent[SuperAgentDeps, SourcedAnswer]) -> None:
    @agent.tool(name="open_message")
    def _message(ctx: RunContext[SuperAgentDeps], ref: str) -> str:
        """Read one whole message with its attachments, by a reference such as m1."""
        return _open(ctx.deps, "a message", ctx.deps.sources.message_id(ref), open_message)

    @agent.tool(name="open_thread")
    def _thread(ctx: RunContext[SuperAgentDeps], ref: str) -> str:
        """Read the whole conversation around a message, both sides, by a reference such as m1."""
        return _open(ctx.deps, "a conversation", ctx.deps.sources.message_id(ref), open_thread)

    @agent.tool(name="open_document")
    def _document(ctx: RunContext[SuperAgentDeps], ref: str, page: int = 1) -> str:
        """Read a document's text page by page, by a reference such as d1."""
        return _open(
            ctx.deps, "a document", ctx.deps.sources.document_id(ref),
            lambda session, company_id, doc_id: open_document(session, company_id, doc_id, page),
        )  # fmt: skip

    @agent.tool(name="open_person")
    def _person(ctx: RunContext[SuperAgentDeps], ref: str) -> str:
        """See a named person's leases and cases, by a reference such as p1."""
        person_id = ctx.deps.people.get(ref.strip().lower())
        text = _open(ctx.deps, "a person", person_id, open_person)
        if person_id is None or NOT_AVAILABLE in text or text == NO_MORE_LOOKUPS:
            return text
        source = ctx.deps.sources.add("data", f"person {person_id}", "Directory")
        return f"reference for this: {source}\n{text}"


def _finish(engine: Engine, row: ModelCall, started: float, deps: SuperAgentDeps, usage: RunUsage | None) -> None:
    """Complete the audit row of a run (success or failure); the steps taken so far are kept either way."""
    row.latency_ms = int((time.perf_counter() - started) * 1000)
    row.output = {**(row.output or {}), "steps": list(deps.steps)}
    if usage is not None:
        row.tokens_in, row.tokens_out = usage.input_tokens, usage.output_tokens
    record_call(engine, row)


def _prepare(deps: SuperAgentDeps, query: str, deadline: float) -> str:
    """Start the clock and hand the model references for the people the question names. Returns their block."""
    deps.tools_until = time.monotonic() + deadline * TOOL_SHARE
    named = named_people(deps.engine, deps.company_id, query)
    deps.people = {f"p{i}": person_id for i, (person_id, _) in enumerate(named, start=1)}
    lines = [f"{ref}: {name}" for ref, (_, name) in zip(deps.people, named, strict=True)]
    return "\n" + data_block("entities", "\n".join(lines)) if lines else ""


def _run_within(
    deadline: float, agent: Agent[SuperAgentDeps, SourcedAnswer], query: str, history: Sequence[str],
    deps: SuperAgentDeps,
) -> AgentRunResult[SourcedAnswer]:  # fmt: skip
    """The run on a worker thread, so a hung provider cannot hold the owner's request past the deadline. A run that is
    given up finishes in the background and its answer is dropped."""
    settings = ModelSettings(timeout=min(deps.settings.llm_timeout_sec, deadline), max_tokens=MAX_TOKENS)
    context = contextvars.copy_context()  # keeps the trace of the turn
    run = _POOL.submit(
        context.run,
        lambda: agent.run_sync(query, deps=deps, message_history=history_messages(history), model_settings=settings),
    )
    return run.result(timeout=deadline)


def run_research(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    system_prompt: str,
    history: Sequence[str],
    query: str,
    *,
    embedder: TextEmbedder | None,
) -> ResearchResult | None:
    if settings.llm_model == "fake":
        return None
    try:
        check_budget(engine, settings, company_id, CONCIERGE_PURPOSE)
    except BudgetExceededError:
        return None
    deps = SuperAgentDeps(engine, settings, company_id, embedder)
    row = new_call(settings, company_id, AGENT_NAME, system_prompt, query)
    started, deadline = time.perf_counter(), settings.super_agent_deadline_sec
    try:
        prompt = system_prompt + _prepare(deps, query, deadline)
        result = _run_within(deadline, _build_agent(settings, prompt), query, history, deps)
    except DeadlineError:
        steps = tuple(deps.steps)
        row.error = "deadline"
        _finish(engine, row, started, deps, None)
        log.warning("superagent.research_deadline", company_id=str(company_id), lookups=len(steps))
        checked = f" Checked so far: {'; '.join(steps)}." if steps else ""
        return ResearchResult(f"{OUT_OF_TIME}{checked} Try a narrower question.", steps)
    except Exception as exc:  # the caller degrades to the plain direct answer
        row.error = f"{type(exc).__name__}: {exc}"[:2000]
        _finish(engine, row, started, deps, None)
        log.warning("superagent.research_failed", company_id=str(company_id), error=describe_model_error(exc))
        return None
    screened = screen(result.output, deps.sources, deps.steps)
    row.output = {"chars": len(screened.answer), "sources": len(screened.sources)}
    _finish(engine, row, started, deps, result.usage)
    return ResearchResult(screened.answer, tuple(deps.steps), screened.sources) if screened.answer else None

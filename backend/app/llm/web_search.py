"""One Google Search through Gemini's grounding tool: the sources it names, never its answer.

The answer text is thrown away. Callers fetch the sources themselves (`app.channels.prices.page_fetch`) and work from
the page text, so nothing the model says about a page is taken on trust. With an engine and company every search is
recorded in `model_calls` and counts against the company's budget; without one (the live check) it is not.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.messages import ModelMessage, NativeToolReturnPart
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.settings import ModelSettings
from sqlalchemy import Engine

from app.contracts import PromptRef
from app.core.errors import AgentFailedError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import ModelCall
from app.llm.budget import check_budget
from app.llm.calls import _cost, _record, is_transient
from app.llm.prompts import load_prompt
from app.llm.render import data_block
from app.llm.runtime import build_model, describe_model_error, model_name_for

NAME = "web_search"
PROMPT = PromptRef(name=NAME, version="v1")
MAX_QUERY_CHARS = 400


@dataclass(frozen=True)
class WebSource:
    url: str  # a Google redirect link: follow it to learn the real page
    title: str


def search_prompt(query: str, region: str) -> str:
    return data_block("data", f"Query: {' '.join(query.split())[:MAX_QUERY_CHARS]}\nCountry: {region}")


def _named(content: Any) -> list[Any]:
    """The grounding sources of a search return: the content itself, or its `sources` beside server-side tool parts."""
    if isinstance(content, dict):
        content = content.get("sources")
    return content if isinstance(content, list) else []


def sources_in(messages: Sequence[ModelMessage]) -> list[WebSource]:
    """Every web source the search tool returned, in order, each address once."""
    found: dict[str, WebSource] = {}
    for message in messages:
        for part in message.parts:
            if not isinstance(part, NativeToolReturnPart) or part.tool_name != WebSearchTool.kind:
                continue
            for item in _named(part.content):
                url = item.get("uri") if isinstance(item, dict) else None
                if isinstance(url, str) and url:
                    found.setdefault(url, WebSource(url, str(item.get("title") or "")))
    return list(found.values())


def _row(settings: Settings, company_id: UUID, sha256: str, prompt: str) -> ModelCall:
    return ModelCall(
        id=new_id(), company_id=company_id, purpose=NAME, prompt_name=NAME, prompt_version=PROMPT.version,
        prompt_sha256=sha256, model=model_name_for(settings, NAME), input={"prompt": prompt},
    )  # fmt: skip


def grounded_search(
    settings: Settings, query: str, region: str, *, engine: Engine | None = None, company_id: UUID | None = None
) -> list[WebSource]:
    """Transient provider errors propagate; any other failure is `AgentFailedError`."""
    loaded, prompt = load_prompt(PROMPT), search_prompt(query, region)
    row = None
    if engine is not None and company_id is not None:
        check_budget(engine, settings, company_id, NAME)
        row = _row(settings, company_id, loaded.sha256, prompt)
    agent = Agent(
        build_model(settings, NAME), instructions=loaded.text, capabilities=[NativeTool(WebSearchTool())]
    )  # fmt: skip
    limits = ModelSettings(timeout=settings.llm_timeout_sec, max_tokens=settings.llm_max_output_tokens)
    started = time.perf_counter()
    try:
        result = agent.run_sync(prompt, model_settings=limits)
    except Exception as exc:
        if row is not None and engine is not None:
            row.latency_ms = int((time.perf_counter() - started) * 1000)
            row.error = f"{type(exc).__name__}: {exc}"[:2000]
            _record(engine, row)
        if is_transient(exc):
            raise
        raise AgentFailedError(f"{NAME}: {describe_model_error(exc)}") from exc
    sources = sources_in(result.all_messages())
    if row is not None and engine is not None:
        row.latency_ms = int((time.perf_counter() - started) * 1000)
        row.output = {"sources": [s.title for s in sources]}
        row.cost_usd = _cost(result)
        row.tokens_in, row.tokens_out = result.usage.input_tokens, result.usage.output_tokens
        _record(engine, row)
    return sources

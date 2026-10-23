"""Retrieval agents (ADR 0008): the query planner and the listwise reranker. No tools, no write access.

Both see untrusted text only inside data blocks (the owner's question in `message`, passages in `excerpts`). The planner
never sees documents. Their outputs only steer a search; nothing they return is shown to the owner or run as an action.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.contracts import PromptRef, QueryPlan, RerankResult
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_QUESTION_CHARS = 400
MAX_PASSAGE_CHARS = 700  # enough to judge a passage; the full chunk is used later for the answer


def _plan(output: QueryPlan, _loaded: LoadedPrompt) -> QueryPlan:
    return output


def _rerank(output: RerankResult, _loaded: LoadedPrompt) -> RerankResult:
    return output


RAG_PLAN = AgentSpec(
    name="rag_plan", prompt=PromptRef(name="rag_plan", version="v1"), output_type=QueryPlan, finalize=_plan
)
RAG_RERANK = AgentSpec(
    name="rag_rerank", prompt=PromptRef(name="rag_rerank", version="v1"), output_type=RerankResult, finalize=_rerank
)


@dataclass(frozen=True)
class RerankItem:
    title: str
    doc_type: str
    document_date: date | None
    page: int | None
    text: str
    context: str | None = None  # the chunk's header: title, type, date, unit, parties, heading, page


def plan_prompt(question: str) -> str:
    return data_block("message", question[:MAX_QUESTION_CHARS])


def _heading(it: RerankItem) -> str:
    """The passage's header as the reranker sees it: who and where it is about, not only what it says."""
    if it.context:
        return one_line(it.context)
    page = f", p.{it.page}" if it.page else ""
    return f"{one_line(it.title)} ({it.doc_type}, {it.document_date or 'undated'}{page})"


def rerank_prompt(question: str, items: Sequence[RerankItem]) -> str:
    entries = [f"[{i}] {_heading(it)}\n{it.text[:MAX_PASSAGE_CHARS]}" for i, it in enumerate(items, start=1)]
    body = "\n\n".join(entries) or "none"
    excerpts = data_block("excerpts", body, len(items) * (MAX_PASSAGE_CHARS + 200))
    return f"{excerpts}\n{data_block('message', question[:MAX_QUESTION_CHARS])}"

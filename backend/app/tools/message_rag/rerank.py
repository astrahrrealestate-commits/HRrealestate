"""What a reader of message hits sees, and the listwise reranker over them (ADR 0008's reranker, reused).

The reranker is one model call: call it after the search session is closed, and only where an answer is worth it
(Astra; not the link check or the inbox search). It only drops a hit the model scored as unhelpful."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Engine

from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.logging import get_logger
from app.core.property_terms import canonical_tokens
from app.core.settings import Settings
from app.llm.agents.rag import MAX_PASSAGE_CHARS, RAG_RERANK, RerankItem, rerank_prompt
from app.llm.calls import CallContext, is_transient, run_agent
from app.pipeline.rag import KEEP_RELEVANCE, RERANK_TOP
from app.tools.message_rag.chunker import LINE_HEAD, plain_body
from app.tools.message_rag.search import MessageChunkHit

log = get_logger(__name__)
HEAD_CHARS = 200


def best_part(text: str, question: str, size: int = MAX_PASSAGE_CHARS) -> str:
    """The stretch of a long text that shares most words with the question. For text without speakers (documents)."""
    last = len(text) - size
    if last <= 0:
        return text
    wanted = set(canonical_tokens(question))
    starts = [
        *range(0, last, max(1, size // 2)),
        last,
    ]  # half steps: an answer on one window's edge is whole in the next
    return max((text[i : i + size] for i in starts), key=lambda part: len(wanted & set(canonical_tokens(part))))


def _line(line: str) -> tuple[str, str]:
    """The stored `[stamp | sender | direction] ` head of a chunk line, and its body without head syntax (chunks from
    before bodies were stored that way)."""
    found = LINE_HEAD.match(line)
    head = found.group(0) if found else ""
    return head[:HEAD_CHARS], plain_body(line[len(head) :])


def best_lines(text: str, question: str, size: int = MAX_PASSAGE_CHARS) -> str:
    """A chunk cut to `size`: whole when it fits, else its best line. Words never appear without the real sender, date
    and direction of their own line."""
    lines = [_line(line) for line in text.split("\n")]
    whole = "\n".join(head + body for head, body in lines)
    if len(whole) <= size:
        return whole
    wanted = set(canonical_tokens(question))
    head, body = max(lines, key=lambda parts: len(wanted & set(canonical_tokens(parts[1]))))
    return head + best_part(body, question, max(1, size - len(head)))


def _item(hit: MessageChunkHit, question: str) -> RerankItem:
    """Server-resolved facts first: the context header starts with a subject its sender chose."""
    facts = f"{hit.last_sent_at:%Y-%m-%d} | {hit.channel} | {hit.person_name or 'unknown'} | {hit.unit_address or '-'}"
    context = f"{facts[:120]} | {hit.context}" if hit.context else facts
    text = best_lines(hit.text, question)
    return RerankItem(hit.channel, "message", hit.last_sent_at.date(), None, text, context)


def rerank_hits(
    engine: Engine, settings: Settings, company_id: UUID, question: str, hits: Sequence[MessageChunkHit]
) -> list[MessageChunkHit]:
    """Hits that help (2) or answer (3) best first, then hits the model did not score, in the fused order. A hit it
    scored 0 or 1 is dropped. Off, failing or scoring nothing: the fused order stands."""
    if not settings.rag_rerank or not hits:
        return list(hits)
    top = list(hits[:RERANK_TOP])
    prompt = rerank_prompt(question, [_item(h, question) for h in top])
    try:
        out = run_agent(engine, settings, RAG_RERANK, prompt, CallContext(company_id, "rag_rerank")).output
    except Exception as exc:
        if not (isinstance(exc, BudgetExceededError | AgentFailedError) or is_transient(exc)):
            raise
        log.warning("message_rag.rerank_degraded", company_id=str(company_id), reason=type(exc).__name__)
        return list(hits)
    relevance = {s.ref: s.relevance for s in out.scores if 1 <= s.ref <= len(top)}
    kept = [(i, h) for i, h in enumerate(top, start=1) if relevance.get(i, KEEP_RELEVANCE) >= KEEP_RELEVANCE]
    return [h for i, h in sorted(kept, key=lambda p: (-relevance.get(p[0], 0), p[0]))]

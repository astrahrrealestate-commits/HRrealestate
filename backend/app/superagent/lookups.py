"""The research loop's lookups: database, messages, documents and the web. Each returns the text the model sees and a
count for the step label; every row and page gets a short reference in the run's `SourceLog`. Read only, company-scoped,
and never a model call inside an open database session."""

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.channels.registry import search_client
from app.context.budget import clip
from app.llm.render import one_line
from app.pipeline.document_search import DocFilter, metadata_hits
from app.pipeline.rag import RERANK_TOP, retrieve_context
from app.superagent.research_base import LOOKUP_FAILED, MAX_HITS, SNIPPET_CHARS, SuperAgentDeps
from app.tools.message_rag.rerank import best_lines, best_part, rerank_hits
from app.tools.message_rag.search import search_messages
from app.tools.query_agent.agent import run_query_agent

MAX_WEB_PAGES = 5


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def database(deps: SuperAgentDeps, question: str) -> tuple[str, int]:
    result = run_query_agent(deps.engine, deps.settings, deps.company_id, question)
    if not result.ok:
        return LOOKUP_FAILED, 0
    display = getattr(result, "display_rows", None)
    if isinstance(display, list) and display:
        return json.dumps(display[:15], ensure_ascii=False), result.row_count
    return result.answer, result.row_count


def parse_iso_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def messages_filtered(
    deps: SuperAgentDeps,
    query: str,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    channel: str | None = None,
) -> tuple[str, int]:
    chan = channel.strip().lower() if isinstance(channel, str) and channel.strip() else None
    if chan not in ("gmail", "whatsapp"):
        chan = None
    df = parse_iso_date(date_from)
    dt = parse_iso_date(date_to)
    return message_lines(deps, query, "%Y-%m-%d %H:%M", channel=chan, date_from=df, date_to=dt)


def messages(deps: SuperAgentDeps, query: str) -> tuple[str, int]:
    return message_lines(deps, query, "%Y-%m-%d")


def snippet(text: str, query: str) -> str:
    return clip(best_part(" ".join(text.split()), query, SNIPPET_CHARS), SNIPPET_CHARS)


def chunk(text: str, query: str) -> str:
    return one_line(best_lines(text, query, SNIPPET_CHARS), SNIPPET_CHARS)


def browse(filters: dict[str, Any]) -> bool:
    return any(v is not None for v in filters.values())


def message_lines(deps: SuperAgentDeps, query: str, stamp: str, **filters: Any) -> tuple[str, int]:
    """Candidates first, then the reranker once the session is closed; a date-only search has no question to rank by."""
    limit = RERANK_TOP if query.strip() else MAX_HITS
    with Session(deps.engine) as session:
        hits = search_messages(session, deps.company_id, query, deps.embedder, limit=limit, **filters)
    if query.strip():
        helpful = rerank_hits(deps.engine, deps.settings, deps.company_id, query, hits)
        # "new messages today" has no passage that answers it: a search with a date or channel lists what it found
        hits = (helpful or (hits if browse(filters) else []))[:MAX_HITS]
    lines = []
    for h in hits:
        who, when = h.person_name or "unknown", h.last_sent_at.strftime(stamp)
        ref = deps.sources.add("message", str(h.first_message_id), f"{who}, {h.channel}, {when[:10]}")
        lines.append(f"[{ref}] {when} {h.channel} | {who} | {h.unit_address or '-'}: {chunk(h.text, query)}")
    return "\n".join(lines), len(lines)


def documents(deps: SuperAgentDeps, query: str) -> tuple[str, int]:
    """The answering passages (plan, hybrid, rerank), then documents whose title or file name holds the query."""
    flt = DocFilter(readable_only=True)
    found = retrieve_context(deps.engine, deps.settings, deps.company_id, query, flt, deps.embedder, fact_first=False)
    rows = [(p.document_id, p.title, p.doc_type, snippet(p.text, query)) for p in found.passages]
    if found.fact is not None:
        f = found.fact
        rows.append((f.document_id, f.title, f.doc_type, f"{f.label}: {f.value}"))
    with Session(deps.engine) as session:
        titled = metadata_hits(session, deps.company_id, query, flt, {r[0] for r in rows}, MAX_HITS)
    rows += [(h.document_id, h.title, h.doc_type, snippet(h.summary or "", query)) for h in titled]
    lines = []
    for doc_id, title, kind, text in rows[:MAX_HITS]:
        ref = deps.sources.add("document", str(doc_id), f"{title} ({kind})")
        lines.append(f"[{ref}] {one_line(title)} ({kind}): {one_line(text, SNIPPET_CHARS)}")
    return "\n".join(lines), len(lines)


def web(deps: SuperAgentDeps, query: str) -> tuple[str, int]:
    """Public pages, each fetched and read by the adapter; untrusted text like mail. Every finding carries its URL."""
    client = search_client(deps.settings, deps.engine, deps.company_id)
    hits = client.search(query, region="nl", limit=MAX_WEB_PAGES)
    lines = []
    for hit in hits[:MAX_WEB_PAGES]:
        ref = deps.sources.add("web", hit.url, one_line(hit.title or hit.url, 120))
        lines.append(f"[{ref}] {one_line(hit.title, 120)} ({hit.url}): {snippet(hit.text, query)}")
    return "\n".join(lines), len(lines)

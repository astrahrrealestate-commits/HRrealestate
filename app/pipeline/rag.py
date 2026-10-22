"""Advanced retrieval for one question (ADR 0008): plan, fact-first, hybrid search, rerank, widen, hand over.

1. A small planner call turns the question into keyword variants in both languages, a hypothetical answer passage
   (HyDE) and, for a single-fact question, the fact it asks for. If it fails or the budget is spent, the glossary and
   the question itself do the job.
2. A fact question is answered from the stored facts of the scoped documents, with no generation, unless the documents
   disagree. Everything else goes on.
3. Hybrid search (words + vectors + document vectors, fused) gives candidates; the reranker scores the best 20 and only
   passages that help (2) or answer (3) go on. Nothing relevant means nothing is passed: the caller says "not found".
4. Chosen chunks are widened with their neighbours, at most three chunks per document and six passages in all.
Planner and reranker failures degrade to the cheaper path and are never an error for the owner.
"""

from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import FactKind, QueryPlan
from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.logging import get_logger
from app.core.property_terms import fold
from app.core.settings import Settings
from app.db.enums import DocumentStatus
from app.db.models import DocumentChunk, DocumentRow
from app.llm.agents.doc_qa import Passage
from app.llm.agents.rag import RAG_PLAN, RAG_RERANK, RerankItem, plan_prompt, rerank_prompt
from app.llm.calls import CallContext, is_transient, run_agent
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_search import SNIPPET_OPTIONS, DocFilter, DocHit, doc_filters, make_hit, metadata_hits
from app.pipeline.rag_retrieval import Candidate, hybrid_candidates, words_query

log = get_logger(__name__)
RERANK_TOP = 20
KEEP_RELEVANCE = 2  # "helps" or better
PER_DOC = 3
MAX_PASSAGES = 6
TYPE_BOOST = 1.15  # candidates of a kind the planner expects
FACT_WORDS: dict[FactKind, tuple[str, ...]] = {
    FactKind.monthly_rent: ("monthly_rent", "rent", "huur", "maandhuur", "kale_huur", "huurprijs"),
    FactKind.deposit: ("deposit", "waarborgsom", "borg"),
    FactKind.notice_period: ("notice", "opzeg"),
    FactKind.lease_start: (),
    FactKind.lease_end: (),
}
_FACT_DATES = {FactKind.lease_start: "start_date", FactKind.lease_end: "end_date"}


@dataclass(frozen=True)
class FactAnswer:
    document_id: UUID
    title: str
    doc_type: str
    document_date: object
    label: str
    value: str


@dataclass(frozen=True)
class RagContext:
    route: str  # "fact" | "hybrid" | "none"
    passages: list[Passage]
    fact: FactAnswer | None = None
    plan: QueryPlan | None = None
    candidates: int = 0
    reranked: bool = False


def _degrade(exc: BaseException, what: str, company_id: UUID) -> None:
    if isinstance(exc, BudgetExceededError | AgentFailedError) or is_transient(exc):
        log.warning("rag.degraded", step=what, company_id=str(company_id), reason=type(exc).__name__)
        return
    raise exc


def plan_question(engine: Engine, settings: Settings, company_id: UUID, question: str) -> QueryPlan | None:
    if not settings.rag_query_rewrite:
        return None
    try:
        return run_agent(engine, settings, RAG_PLAN, plan_prompt(question), CallContext(company_id, "rag_plan")).output
    except Exception as exc:
        _degrade(exc, "plan", company_id)
        return None


def rerank(
    engine: Engine, settings: Settings, company_id: UUID, question: str, cands: list[Candidate]
) -> dict[UUID, int] | None:
    """Relevance 0-3 per candidate chunk, or None when reranking is off or failed (the fused order then stands)."""
    if not settings.rag_rerank or len(cands) < 2:
        return None
    items = [RerankItem(c.title, c.doc_type, c.document_date, c.page, c.text, c.context) for c in cands]
    try:
        out = run_agent(
            engine, settings, RAG_RERANK, rerank_prompt(question, items), CallContext(company_id, "rag_rerank")
        ).output
    except Exception as exc:
        _degrade(exc, "rerank", company_id)
        return None
    scored = {s.ref: s.relevance for s in out.scores if 1 <= s.ref <= len(cands)}
    return {c.chunk_id: scored.get(i, 0) for i, c in enumerate(cands, start=1)}


def lookup_fact(session: Session, company_id: UUID, flt: DocFilter, kind: FactKind) -> FactAnswer | None:
    """The fact from the stored facts of the scoped, filed documents; None when absent or the documents disagree."""
    scope = replace(flt, status=DocumentStatus.filed, readable_only=True)
    stmt = select(DocumentRow).where(*doc_filters(company_id, scope), DocumentRow.facts.is_not(None))
    found: list[tuple[DocumentRow, str, str]] = []
    for doc in session.scalars(
        stmt.order_by(DocumentRow.document_date.desc().nulls_last(), DocumentRow.created_at.desc())
    ):
        facts = doc.facts or {}
        if kind in _FACT_DATES and doc.doc_type == "lease" and facts.get(_FACT_DATES[kind]):
            found.append((doc, kind.value, str(facts[_FACT_DATES[kind]])))
            continue
        for fact in facts.get("key_facts", []):
            if any(w in fold(fact["label"]) for w in FACT_WORDS[kind]):
                found.append((doc, fact["label"], fact["value"]))
                break
    if not found or len({value.lower() for _, _, value in found}) != 1:
        return None
    doc, label, value = found[0]
    return FactAnswer(doc.id, doc.title, doc.doc_type, doc.document_date, label, value)


def _neighbours(session: Session, company_id: UUID, picks: list[Candidate]) -> dict[tuple[UUID, int], DocumentChunk]:
    wanted = {(c.document_id, o) for c in picks for o in (c.ord - 1, c.ord, c.ord + 1) if o >= 0}
    docs = {d for d, _ in wanted}
    rows = session.scalars(
        select(DocumentChunk).where(DocumentChunk.company_id == company_id, DocumentChunk.document_id.in_(docs))
    )
    return {(r.document_id, r.ord): r for r in rows if (r.document_id, r.ord) in wanted}


def passages_from(session: Session, company_id: UUID, picks: list[Candidate]) -> list[Passage]:
    """Merge each document's chosen chunks and their neighbours into runs of consecutive chunks: one passage per run."""
    chunks = _neighbours(session, company_id, picks)
    best: dict[UUID, float] = {}
    for c in picks:
        best[c.document_id] = max(best.get(c.document_id, 0.0), c.score)
    meta = {c.document_id: c for c in picks}
    passages: list[Passage] = []
    for doc_id in sorted(best, key=lambda d: -best[d]):
        ords = sorted({o for (d, o) in chunks if d == doc_id})
        run: list[int] = []
        for o in [*ords, None]:
            if o is not None and (not run or o == run[-1] + 1):
                run.append(o)
                continue
            if run:
                parts = [chunks[(doc_id, r)] for r in run]
                m = meta[doc_id]
                pages = tuple(sorted({p.page for p in parts if p.page}))
                passages.append(Passage(doc_id, m.title, m.doc_type, m.document_date, "\n".join(p.text for p in parts),
                                        best[doc_id], pages, run[0]))  # fmt: skip
            run = [o] if o is not None else []
    return passages[:MAX_PASSAGES]


def choose(cands: list[Candidate], relevance: dict[UUID, int] | None) -> list[Candidate]:
    """Reranked: only chunks that help or answer, best first. Not reranked: the fused order. At most PER_DOC per
    document and MAX_PASSAGES chunks in all."""
    if relevance is not None:
        ordered = sorted((c for c in cands if relevance.get(c.chunk_id, 0) >= KEEP_RELEVANCE),
                         key=lambda c: (-relevance[c.chunk_id], -c.score))  # fmt: skip
    else:
        ordered = list(cands)
    per_doc: dict[UUID, int] = {}
    picked: list[Candidate] = []
    for c in ordered:
        if per_doc.get(c.document_id, 0) < PER_DOC and len(picked) < MAX_PASSAGES:
            per_doc[c.document_id] = per_doc.get(c.document_id, 0) + 1
            picked.append(c)
    return picked


def retrieve_context(engine: Engine, settings: Settings, company_id: UUID, question: str, flt: DocFilter,
                     embedder: TextEmbedder | None) -> RagContext:  # fmt: skip
    with Session(engine) as session:
        if session.scalar(select(DocumentRow.id).where(*doc_filters(company_id, flt)).limit(1)) is None:
            return RagContext("none", [])  # nothing in scope: no model call, no cost
    plan = plan_question(engine, settings, company_id, question)
    with Session(engine) as session:
        if plan and plan.fact is not None and (fact := lookup_fact(session, company_id, flt, plan.fact)):
            return RagContext("fact", [], fact, plan)
        cands = hybrid_candidates(
            session, company_id, question, flt, embedder,
            variants=plan.keywords if plan else (), dense_texts=[plan.hypothetical_answer] if plan else (),
        )  # fmt: skip
        if plan and plan.doc_types:
            expected = {t.value for t in plan.doc_types}
            cands = sorted((replace(c, score=c.score * (TYPE_BOOST if c.doc_type in expected else 1.0)) for c in cands),
                           key=lambda c: -c.score)  # fmt: skip
        top = cands[:RERANK_TOP]
        relevance = rerank(engine, settings, company_id, question, top)
        picks = choose(top, relevance)
        passages = passages_from(session, company_id, picks) if picks else []
    return RagContext("hybrid" if passages else "none", passages, None, plan, len(cands), relevance is not None)


def safe_hybrid(session: Session, company_id: UUID, question: str, flt: DocFilter,
                embedder: TextEmbedder | None) -> list[Candidate]:  # fmt: skip
    """Hybrid candidates with no language-model call. A failing embedding provider is not an error: the words list
    answers alone (the same call without vectors)."""
    try:
        return hybrid_candidates(session, company_id, question, flt, embedder)
    except Exception as exc:
        if embedder is None or not is_transient(exc):
            raise
        log.warning("rag.embedder_degraded", company_id=str(company_id), reason=type(exc).__name__)
        return hybrid_candidates(session, company_id, question, flt, None)


def retrieve_cheap(session: Session, company_id: UUID, question: str, flt: DocFilter, embedder: TextEmbedder | None,
                   limit: int = 3) -> list[Passage]:  # fmt: skip
    """Hybrid passages with no language-model call: for every inbound message, where cost per message matters."""
    cands = safe_hybrid(session, company_id, question, flt, embedder)
    picks = choose(cands[:RERANK_TOP], None)[:limit]
    return passages_from(session, company_id, picks) if picks else []


def _highlights(session: Session, chunk_ids: list[UUID], query: str) -> dict[UUID, str]:
    """`«matched»` words in a short fragment of each chunk, for the chunks the words side recognises."""
    if not chunk_ids:
        return {}
    fragment = func.ts_headline("dutch", DocumentChunk.text, func.websearch_to_tsquery("dutch", query), SNIPPET_OPTIONS)
    rows = session.execute(select(DocumentChunk.id, fragment).where(DocumentChunk.id.in_(chunk_ids)))
    return {cid: " ".join(text.split()) for cid, text in rows if "«" in text}


def search_hybrid(session: Session, company_id: UUID, query: str, flt: DocFilter, embedder: TextEmbedder | None,
                  limit: int = 20) -> list[DocHit]:  # fmt: skip
    """The library's typed search: documents ranked by their best chunk across words and vectors, then by what they are
    called. No language-model call. The snippet is the opening of the best chunk (untrusted text)."""
    best: dict[UUID, Candidate] = {}
    for c in safe_hybrid(session, company_id, query, flt, embedder):
        best.setdefault(c.document_id, c)
    docs = {d.id: d for d in session.scalars(select(DocumentRow).where(DocumentRow.id.in_(list(best))))}
    top = sorted(best.values(), key=lambda c: -c.score)[:limit]
    marked = _highlights(session, [c.chunk_id for c in top], words_query(query))
    hits = [
        make_hit(docs[c.document_id], marked.get(c.chunk_id) or " ".join(c.text.split())[:240], c.score)
        for c in top
        if c.document_id in docs
    ]
    if len(hits) < limit:
        hits += metadata_hits(session, company_id, query, flt, {h.document_id for h in hits}, limit - len(hits))
    return hits

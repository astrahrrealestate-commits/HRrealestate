"""Hybrid retrieval over document chunks (ADR 0008): full-text list + vector lists + document-level vector, fused.

Every list is a ranking of chunk ids under the same company, status, suspicious and link filters as the rest of the
library. Reciprocal Rank Fusion combines them without comparing their incompatible scores: a chunk high in several
lists wins, and one strong list is enough to surface a chunk. Without vectors (not embedded yet, or no embedder) the
words list still answers. Everything returned is untrusted document text.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.property_terms import expand
from app.db.models import DocumentChunk, DocumentRow
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_search import DocFilter, any_of, doc_filters, to_tsquery

log = get_logger(__name__)
RRF_K = 60
CANDIDATES = 40  # per list
WEIGHT_WORDS = 1.0
WEIGHT_VECTOR = 1.0
WEIGHT_DOCUMENT = 0.5  # a chunk of a document that is itself a good match gets a nudge, not a ticket


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    document_id: UUID
    ord: int
    page: int | None
    heading: str | None
    text: str
    title: str
    doc_type: str
    document_date: date | None
    score: float
    context: str | None = None
    words_rank: int | None = None
    vector_rank: int | None = None


def rrf(lists: Sequence[tuple[float, Sequence[UUID]]], k: int = RRF_K) -> dict[UUID, float]:
    """Reciprocal Rank Fusion: each (weight, ranking) adds weight / (k + rank) to every id it contains."""
    fused: dict[UUID, float] = defaultdict(float)
    for weight, ranking in lists:
        for rank, item in enumerate(ranking, start=1):
            fused[item] += weight / (k + rank)
    return dict(fused)


def words_query(question: str, variants: Sequence[str] = ()) -> str:
    """One OR-query: the question's words, the model's variants, and the other language's words from the glossary."""
    joined = " ".join([question, *variants])
    return any_of(" ".join([joined, *expand(joined)]))


def words_ranking(session: Session, company_id: UUID, query: str, flt: DocFilter, k: int = CANDIDATES) -> list[UUID]:
    tsq = to_tsquery(query)
    rank = func.ts_rank_cd(DocumentChunk.tsv, tsq)
    stmt = (
        select(DocumentChunk.id)
        .join(DocumentRow, DocumentRow.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == company_id, DocumentChunk.tsv.op("@@")(tsq), *doc_filters(company_id, flt))
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(k)
    )
    return list(session.scalars(stmt))


def _widen_index_search(session: Session) -> None:
    """Let the HNSW scan keep looking when filters discard rows (pgvector 0.8+); older versions ignore the attempt."""
    for setting in ("hnsw.iterative_scan = 'relaxed_order'", "hnsw.ef_search = 100"):
        try:
            with session.begin_nested():
                session.execute(text(f"SET LOCAL {setting}"))
        except Exception:  # noqa: S110  (an unknown setting on an older pgvector is not an error)
            pass


def vector_ranking(session: Session, company_id: UUID, vector: Sequence[float], flt: DocFilter,
                   k: int = CANDIDATES) -> list[UUID]:  # fmt: skip
    _widen_index_search(session)
    stmt = (
        select(DocumentChunk.id)
        .join(DocumentRow, DocumentRow.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.company_id == company_id, DocumentChunk.embedding.is_not(None), *doc_filters(company_id, flt)
        )
        .order_by(DocumentChunk.embedding.cosine_distance(list(vector)), DocumentChunk.id)
        .limit(k)
    )
    return list(session.scalars(stmt))


def document_ranking(
    session: Session, company_id: UUID, vector: Sequence[float], flt: DocFilter, k: int = 10
) -> list[UUID]:
    stmt = (
        select(DocumentRow.id)
        .where(DocumentRow.doc_embedding.is_not(None), *doc_filters(company_id, flt))
        .order_by(DocumentRow.doc_embedding.cosine_distance(list(vector)), DocumentRow.id)
        .limit(k)
    )
    return list(session.scalars(stmt))


def _load(
    session: Session, company_id: UUID, scores: dict[UUID, float], ranks: dict[str, dict[UUID, int]]
) -> list[Candidate]:
    rows = session.execute(
        select(DocumentChunk, DocumentRow)
        .join(DocumentRow, DocumentRow.id == DocumentChunk.document_id)
        .where(DocumentChunk.company_id == company_id, DocumentChunk.id.in_(list(scores)))
    ).all()
    out = [
        Candidate(c.id, d.id, c.ord, c.page, c.heading, c.text, d.title, d.doc_type, d.document_date, scores[c.id],
                  c.context, ranks["words"].get(c.id), ranks["vector"].get(c.id))
        for c, d in rows
    ]  # fmt: skip
    return sorted(out, key=lambda c: (-c.score, c.document_id, c.ord))


def _embed(embedder: TextEmbedder | None, texts: list[str], company_id: UUID) -> list[list[float]] | None:
    """Query vectors, or None when there is no embedder or the provider fails for any reason (a bad key, a quota, a
    timeout): the words list then answers alone. Logged at error level with the class only."""
    if embedder is None:
        return None
    try:
        return embedder.embed_documents(texts)
    except Exception as exc:
        log.error("rag.embedder_failed", company_id=str(company_id), reason=type(exc).__name__)
        return None


def hybrid_candidates(
    session: Session, company_id: UUID, question: str, flt: DocFilter, embedder: TextEmbedder | None = None,
    variants: Sequence[str] = (), dense_texts: Sequence[str] = (), k: int = CANDIDATES,
) -> list[Candidate]:  # fmt: skip
    """The fused candidate chunks for a question, best first. `variants` extend the words side, `dense_texts` (the
    question itself is always one) the vector side: a hypothetical answer passage (HyDE) goes there."""
    vectors = _embed(embedder, [question, *[t for t in dense_texts if t.strip()]], company_id)  # before any query
    words = words_ranking(session, company_id, words_query(question, variants), flt, k)
    lists: list[tuple[float, Sequence[UUID]]] = [(WEIGHT_WORDS, words)]
    ranks: dict[str, dict[UUID, int]] = {"words": {c: i for i, c in enumerate(words, 1)}, "vector": {}}
    if vectors:
        for vector in vectors:
            ranking = vector_ranking(session, company_id, vector, flt, k)
            lists.append((WEIGHT_VECTOR, ranking))
            for i, c in enumerate(ranking, 1):
                ranks["vector"].setdefault(c, i)
        fused_docs = document_ranking(session, company_id, vectors[0], flt)
        doc_boost = {d: WEIGHT_DOCUMENT / (RRF_K + i) for i, d in enumerate(fused_docs, 1)}
    else:
        doc_boost = {}
    scores = rrf(lists)
    if not scores:
        return []
    if doc_boost:
        rows = session.execute(
            select(DocumentChunk.id, DocumentChunk.document_id).where(
                DocumentChunk.company_id == company_id, DocumentChunk.id.in_(list(scores))
            )
        )
        owner = {row[0]: row[1] for row in rows}
        scores = {c: s + doc_boost.get(owner.get(c, c), 0.0) for c, s in scores.items()}
    top = dict(sorted(scores.items(), key=lambda kv: -kv[1])[:k])
    return _load(session, company_id, top, ranks)

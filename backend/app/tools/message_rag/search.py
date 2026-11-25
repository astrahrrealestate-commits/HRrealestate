"""Hybrid search (BM25 + pgvector HNSW) and thread context retrieval for Message RAG."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import MessageChunk, Person, Unit
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_search import to_tsquery
from app.pipeline.rag_retrieval import rrf, words_query
from app.tools.message_rag.threads import get_message_window, get_thread_timeline

__all__ = ["MessageChunkHit", "get_message_window", "get_thread_timeline", "search_messages"]

log = get_logger(__name__)

RRF_K = 60
WEIGHT_ALL_WORDS = 1.0
WEIGHT_WORDS = 1.0
WEIGHT_VECTOR = 1.0
TOP_CANDIDATES = 40
# Words of every chunk's own header and line heads: as search terms they match everything and mean nothing.
_BOILERPLATE = frozenset(
    [
        "channel",
        "thread",
        "tenant",
        "property",
        "case",
        "context",
        "subject",
        "gmail",
        "whatsapp",
        "inbound",
        "outbound",
        "owner",
        "harjot",
    ]
)


@dataclass(frozen=True)
class MessageChunkHit:
    chunk_id: UUID
    first_message_id: UUID
    last_message_id: UUID
    message_ids: list[UUID]
    channel: str
    thread_ref: str
    text: str
    context: str | None
    first_sent_at: datetime
    last_sent_at: datetime
    person_id: UUID | None
    person_name: str | None
    unit_id: UUID | None
    unit_address: str | None
    case_ids: list[UUID]
    score: float


def _filter_conditions(
    company_id: UUID,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    case_id: UUID | None = None,
    channel: str | None = None,
    direction: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [MessageChunk.company_id == company_id]

    if person_id is not None:
        conds.append(
            or_(
                MessageChunk.person_id == person_id,
                MessageChunk.participant_ids.contains([person_id]),
            )
        )
    if unit_id is not None:
        conds.append(MessageChunk.unit_id == unit_id)
    if case_id is not None:
        conds.append(MessageChunk.case_ids.contains([case_id]))
    if channel is not None:
        conds.append(MessageChunk.channel == channel)
    if direction == "inbound":
        conds.append(MessageChunk.has_inbound.is_(True))
    elif direction == "outbound":
        conds.append(MessageChunk.has_outbound.is_(True))

    if date_from is not None:
        conds.append(func.date(MessageChunk.last_sent_at) >= date_from)
    if date_to is not None:
        conds.append(func.date(MessageChunk.first_sent_at) <= date_to)

    return conds


def _any_words(query: str) -> str:
    words = words_query(query).split(" or ")
    return " or ".join(w for w in words if w not in _BOILERPLATE)


def _word_ids(session: Session, conds: Sequence[ColumnElement[bool]], query: str) -> list[UUID]:
    if not query.strip():
        return []
    tsq = to_tsquery(query)
    stmt = (
        select(MessageChunk.id)
        .where(*conds, MessageChunk.tsv.op("@@")(tsq))
        .order_by(func.ts_rank_cd(MessageChunk.tsv, tsq).desc(), MessageChunk.last_sent_at.desc())
        .limit(TOP_CANDIDATES)
    )
    return list(session.scalars(stmt))


def search_messages(
    session: Session,
    company_id: UUID,
    query: str,
    embedder: TextEmbedder | None = None,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    case_id: UUID | None = None,
    channel: str | None = None,
    direction: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 8,
) -> list[MessageChunkHit]:
    """Hybrid full-text and vector search across message_chunks using RRF fusion."""
    conds = _filter_conditions(company_id, person_id, unit_id, case_id, channel, direction, date_from, date_to)

    clean_q = query.strip()
    if not clean_q:
        # Date-only sort when no query text is provided
        chunks = session.scalars(
            select(MessageChunk).where(*conds).order_by(MessageChunk.last_sent_at.desc()).limit(limit)
        ).all()
        return [_load_hit(session, c, 1.0) for c in chunks]

    # 1. Full-text search: chunks with every word as typed, then chunks with any of its words
    all_ids = _word_ids(session, conds, clean_q)
    any_ids = _word_ids(session, conds, _any_words(clean_q))

    # 2. Vector search (pgvector HNSW)
    vector_ids: list[UUID] = []
    if embedder is not None:
        try:
            vec = embedder.embed_query(clean_q)
            stmt = (
                select(MessageChunk.id)
                .where(*conds, MessageChunk.embedding.is_not(None))
                .order_by(MessageChunk.embedding.cosine_distance(vec))
                .limit(TOP_CANDIDATES)
            )
            with session.begin_nested():  # a failing query must not take the words side with it
                vector_ids = list(session.scalars(stmt))
        except Exception as exc:  # fall back to words-only on embedding failure
            log.warning("message_rag.vector_search_failed", error=type(exc).__name__)

    # 3. RRF Fusion
    lists: list[tuple[float, Sequence[UUID]]] = []
    if all_ids:
        lists.append((WEIGHT_ALL_WORDS, all_ids))
    if any_ids:
        lists.append((WEIGHT_WORDS, any_ids))
    if vector_ids:
        lists.append((WEIGHT_VECTOR, vector_ids))

    if not lists:
        return []

    scores = rrf(lists, k=RRF_K)
    sorted_ids = sorted(scores.keys(), key=lambda cid: -scores[cid])[:limit]

    if not sorted_ids:
        return []

    chunks_by_id = {
        c.id: c
        for c in session.scalars(
            select(MessageChunk).where(
                MessageChunk.company_id == company_id,
                MessageChunk.id.in_(sorted_ids),
            )
        )
    }

    hits: list[MessageChunkHit] = []
    for cid in sorted_ids:
        chunk = chunks_by_id.get(cid)
        if chunk:
            hits.append(_load_hit(session, chunk, scores[cid]))
    return hits


def _load_hit(session: Session, c: MessageChunk, score: float) -> MessageChunkHit:
    cid = c.company_id
    person_name = session.scalar(select(Person.display_name).where(Person.company_id == cid, Person.id == c.person_id))
    unit_address = session.scalar(select(Unit.address).where(Unit.company_id == cid, Unit.id == c.unit_id))
    return MessageChunkHit(
        chunk_id=c.id,
        first_message_id=c.first_message_id,
        last_message_id=c.last_message_id,
        message_ids=list(c.message_ids),
        channel=c.channel,
        thread_ref=c.thread_ref,
        text=c.text,
        context=c.context,
        first_sent_at=c.first_sent_at,
        last_sent_at=c.last_sent_at,
        person_id=c.person_id,
        person_name=person_name,
        unit_id=c.unit_id,
        unit_address=unit_address,
        case_ids=list(c.case_ids),
        score=score,
    )

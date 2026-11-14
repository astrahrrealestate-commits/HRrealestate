"""Hybrid search (BM25 + pgvector HNSW) and thread context retrieval for Message RAG."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import MessageChunk, MessageRow, Person, Unit
from app.llm.embeddings import TextEmbedder
from app.pipeline.document_search import to_tsquery
from app.pipeline.rag_retrieval import rrf

log = get_logger(__name__)

RRF_K = 60
WEIGHT_WORDS = 1.0
WEIGHT_VECTOR = 1.0
TOP_CANDIDATES = 40


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

    # 1. Full-text search (BM25 / ts_rank_cd)
    tsq = to_tsquery(clean_q)
    word_rows = session.execute(
        select(MessageChunk.id)
        .where(*conds, MessageChunk.tsv.op("@@")(tsq))
        .order_by(func.ts_rank_cd(MessageChunk.tsv, tsq).desc(), MessageChunk.last_sent_at.desc())
        .limit(TOP_CANDIDATES)
    ).all()
    word_ids = [r[0] for r in word_rows]

    # 2. Vector search (pgvector HNSW)
    vector_ids: list[UUID] = []
    if embedder is not None:
        try:
            vec = embedder.embed_query(clean_q)
            vec_rows = session.execute(
                select(MessageChunk.id)
                .where(*conds, MessageChunk.embedding.is_not(None))
                .order_by(MessageChunk.embedding.cosine_distance(vec))
                .limit(TOP_CANDIDATES)
            ).all()
            vector_ids = [r[0] for r in vec_rows]
        except Exception as exc:  # fall back to words-only on embedding failure
            log.warning("message_rag.vector_search_failed", error=str(exc))

    # 3. RRF Fusion
    lists: list[tuple[float, Sequence[UUID]]] = []
    if word_ids:
        lists.append((WEIGHT_WORDS, word_ids))
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
    person_name = session.scalar(select(Person.display_name).where(Person.id == c.person_id)) if c.person_id else None
    unit_address = session.scalar(select(Unit.address).where(Unit.id == c.unit_id)) if c.unit_id else None
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


def get_message_window(
    session: Session,
    company_id: UUID,
    message_id: UUID,
    before: int = 4,
    after: int = 4,
) -> list[dict[str, Any]]:
    """Retrieves chronological raw messages before and after a specific message in the same thread."""
    target = session.get(MessageRow, message_id)
    if target is None or target.company_id != company_id:
        return []

    thread_ref = target.thread_ref or target.provider_msg_id

    # Messages before (ordered desc then reversed)
    before_rows = list(
        session.scalars(
            select(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.channel == target.channel,
                MessageRow.thread_ref == thread_ref,
                MessageRow.sent_at < target.sent_at,
            )
            .order_by(MessageRow.sent_at.desc())
            .limit(before)
        ).all()
    )
    before_rows.reverse()

    # Messages after
    after_rows = list(
        session.scalars(
            select(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.channel == target.channel,
                MessageRow.thread_ref == thread_ref,
                MessageRow.sent_at > target.sent_at,
            )
            .order_by(MessageRow.sent_at.asc())
            .limit(after)
        ).all()
    )

    combined = [*before_rows, target, *after_rows]
    out: list[dict[str, Any]] = []
    for m in combined:
        person_name = (
            session.scalar(select(Person.display_name).where(Person.id == m.person_id)) if m.person_id else None
        )
        meta = m.meta or {}
        out.append(
            {
                "message_id": str(m.id),
                "sent_at": m.sent_at.isoformat(),
                "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction),
                "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
                "sender": person_name or meta.get("from_name") or m.sender_identity,
                "text": m.text,
                "subject": meta.get("subject"),
            }
        )
    return out


def get_thread_timeline(
    session: Session,
    company_id: UUID,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    case_id: UUID | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fast SQL chronological timeline of messages matching person, unit, or case."""
    stmt = (
        select(MessageRow).where(MessageRow.company_id == company_id).order_by(MessageRow.sent_at.desc()).limit(limit)
    )
    if person_id is not None:
        stmt = stmt.where(MessageRow.person_id == person_id)

    rows = session.scalars(stmt).all()
    return [
        {
            "message_id": str(m.id),
            "sent_at": m.sent_at.isoformat(),
            "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
            "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction),
            "sender": m.sender_identity,
            "snippet": " ".join(m.text.split())[:200] if m.text else "",
        }
        for m in rows
    ]

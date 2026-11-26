"""Core indexing engine for Message RAG.

Takes inbound and outbound messages, groups them into conversational chunks under a per-thread lock, and embeds the
chunk. Indexing a message again rebuilds its chunk from its messages as they are now, so a corrected sender, direction,
person or case replaces the old one, a message the gate now refuses leaves, and nothing is ever repeated.
"""

from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.contracts import Direction
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import MessageIndexStatus
from app.db.models import MessageChunk, MessageIndexState, MessageRow, UnderstandingRow
from app.llm.embeddings import build_embedder
from app.tools.message_rag.chunker import (
    compute_content_hash,
    format_context_header,
    should_start_new_chunk,
)
from app.tools.message_rag.gate import should_index_message
from app.tools.message_rag.lines import merge_lines, message_lines
from app.tools.message_rag.resolve import MessageFacts, resolve_facts

log = get_logger(__name__)


def index_message(engine: Engine, settings: Settings, message_id: UUID) -> str:
    """Index one message: "indexed" | "skipped" | "failed" (stored for words, but without a vector)."""
    with Session(engine) as session, session.begin():
        # FOR SHARE: an erasure of this message waits, so its later chunk delete sees the chunk written here.
        msg = session.get(MessageRow, message_id, with_for_update={"read": True})
        if msg is None:
            return "failed"
        _lock_thread(session, msg)
        refusal = _refusal(session, msg)
        held = _held(session, msg)
        before = held.text if held is not None else None
        chunk = _rebuild(session, held) if held is not None else None
        if refusal is not None:
            if chunk is not None:
                _embed_if_needed(chunk, before, settings)
            _record_state(session, msg, MessageIndexStatus.skipped, reason=refusal)
            return "skipped"
        if chunk is None:
            chunk, before = _place(session, msg)
        session.flush()
        error = _embed_if_needed(chunk, before, settings)
        status = MessageIndexStatus.indexed if error is None else MessageIndexStatus.failed
        _record_state(session, msg, status, chunk_id=chunk.id, error=error)
        log.info("message_rag.indexed", message_id=str(message_id), chunk_id=str(chunk.id), status=status.value)
    return status.value


def _refusal(session: Session, msg: MessageRow) -> str | None:
    understanding = session.scalar(
        select(UnderstandingRow).where(
            UnderstandingRow.company_id == msg.company_id, UnderstandingRow.message_id == msg.id
        )
    )
    allowed, reason = should_index_message(msg, understanding)
    return None if allowed else reason or "refused"


def _thread(msg: MessageRow) -> tuple[str, str]:
    return msg.channel.value, msg.thread_ref or msg.provider_msg_id


def _lock_thread(session: Session, msg: MessageRow) -> None:
    channel, thread_ref = _thread(msg)
    key = f"{msg.company_id}:{channel}:{thread_ref}"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})


def _held(session: Session, msg: MessageRow) -> MessageChunk | None:
    channel, thread_ref = _thread(msg)
    return session.scalar(
        select(MessageChunk)
        .where(
            MessageChunk.company_id == msg.company_id,
            MessageChunk.channel == channel,
            MessageChunk.thread_ref == thread_ref,
            MessageChunk.message_ids.contains([msg.id]),
        )
        .order_by(MessageChunk.first_sent_at)
        .limit(1)
    )


def _rebuild(session: Session, chunk: MessageChunk) -> MessageChunk | None:
    """The chunk as its messages are now; deleted (None) when none of them may be indexed any more."""
    rows = {
        m.id: m
        for m in session.scalars(
            select(MessageRow).where(MessageRow.company_id == chunk.company_id, MessageRow.id.in_(chunk.message_ids))
        )
    }
    kept = [rows[i] for i in chunk.message_ids if i in rows and _refusal(session, rows[i]) is None]
    if not kept:
        session.delete(chunk)
        session.flush()
        return None
    facts = [resolve_facts(session, m) for m in kept]
    lines: list[str] = []
    for m, f in zip(kept, facts, strict=True):
        lines += merge_lines(lines, message_lines(session, m, f.person_name))
    chunk.message_ids = [m.id for m in kept]
    chunk.first_message_id, chunk.last_message_id = kept[0].id, kept[-1].id
    chunk.first_sent_at, chunk.last_sent_at = min(m.sent_at for m in kept), max(m.sent_at for m in kept)
    chunk.has_outbound = any(m.direction is Direction.outbound for m in kept)
    chunk.has_inbound = any(m.direction is not Direction.outbound for m in kept)
    chunk.text = "\n".join(lines)
    chunk.person_id = chunk.unit_id = chunk.lease_id = chunk.subject = None
    chunk.participant_ids, chunk.case_ids = [], []
    for f in facts:
        _apply_facts(chunk, f)
    return chunk


def _place(session: Session, msg: MessageRow) -> tuple[MessageChunk, str | None]:
    """A message seen for the first time: the thread's open chunk when it fits, else a new one. With the text before."""
    facts = resolve_facts(session, msg)
    lines = message_lines(session, msg, facts.person_name)
    channel, thread_ref = _thread(msg)
    open_chunk = session.scalar(
        select(MessageChunk)
        .where(
            MessageChunk.company_id == msg.company_id,
            MessageChunk.channel == channel,
            MessageChunk.thread_ref == thread_ref,
            MessageChunk.is_open.is_(True),
        )
        .order_by(MessageChunk.last_sent_at.desc())
        .limit(1)
    )
    if open_chunk is not None:
        before, last = open_chunk.text, open_chunk.last_sent_at
        line = "\n".join(merge_lines(before.split("\n"), lines))
        if not should_start_new_chunk(len(before), len(line), last, msg.sent_at, open_chunk.is_open):
            _append(open_chunk, msg, line)
            _apply_facts(open_chunk, facts)
            return open_chunk, before
        open_chunk.is_open = False
        session.flush()
    chunk = _new_chunk(msg, "\n".join(merge_lines([], lines)), facts)
    session.add(chunk)
    return chunk, None


def _new_chunk(msg: MessageRow, line: str, facts: MessageFacts) -> MessageChunk:
    channel, thread_ref = _thread(msg)
    is_outbound = msg.direction is Direction.outbound
    chunk = MessageChunk(
        id=new_id(),
        company_id=msg.company_id,
        channel=channel,
        thread_ref=thread_ref,
        message_ids=[msg.id],
        first_message_id=msg.id,
        last_message_id=msg.id,
        participant_ids=[],
        case_ids=[],
        has_inbound=not is_outbound,
        has_outbound=is_outbound,
        first_sent_at=msg.sent_at,
        last_sent_at=msg.sent_at,
        text=line,
        content_hash="",
        is_open=True,
    )
    _apply_facts(chunk, facts)
    return chunk


def _append(chunk: MessageChunk, msg: MessageRow, line: str) -> None:
    chunk.message_ids = [*chunk.message_ids, msg.id]
    chunk.last_message_id = msg.id
    chunk.last_sent_at = max(chunk.last_sent_at, msg.sent_at)
    if msg.direction is Direction.outbound:
        chunk.has_outbound = True
    else:
        chunk.has_inbound = True
    chunk.text = f"{chunk.text}\n{line}"


def _apply_facts(chunk: MessageChunk, facts: MessageFacts) -> None:
    if facts.person_id and facts.person_id not in chunk.participant_ids:
        chunk.participant_ids = [*chunk.participant_ids, facts.person_id]
    if facts.case_id and facts.case_id not in chunk.case_ids:
        chunk.case_ids = [*chunk.case_ids, facts.case_id]
    chunk.person_id = chunk.person_id or facts.person_id
    chunk.unit_id = chunk.unit_id or facts.unit_id
    chunk.lease_id = chunk.lease_id or facts.lease_id
    chunk.subject = chunk.subject or facts.subject
    chunk.context = format_context_header(
        chunk.channel,
        chunk.thread_ref,
        facts.subject or chunk.subject,
        facts.person_name,
        facts.unit_address,
        facts.case_summary,
    )


def _embed_if_needed(chunk: MessageChunk, before: str | None, settings: Settings) -> str | None:
    """Stored text is a document, never a query. A chunk whose content and model did not change is left alone. On
    failure: the error class; the old vector stays only when the text it stands for did not change."""
    content_hash = compute_content_hash(chunk.context, chunk.text)
    current = chunk.embedding is not None and chunk.embed_model == settings.embedding_model
    if current and chunk.content_hash == content_hash:
        return None
    embedder = build_embedder(settings)  # a configuration error is not an outage: let it raise
    try:
        [vector] = embedder.embed_documents([f"{chunk.context or ''}\n{chunk.text}"])
    except Exception as exc:
        log.warning("message_rag.embed_failed", error=type(exc).__name__, chunk_id=str(chunk.id))
        if before != chunk.text:
            chunk.embedding = None  # an old vector would answer for text it never saw
        return type(exc).__name__
    chunk.content_hash = content_hash
    chunk.embedding = vector
    chunk.embed_model = settings.embedding_model
    chunk.embed_dim = len(vector)
    return None


def _record_state(
    session: Session,
    msg: MessageRow,
    status: MessageIndexStatus,
    reason: str | None = None,
    chunk_id: UUID | None = None,
    error: str | None = None,
) -> None:
    state = session.get(MessageIndexState, msg.id)
    if state is None:
        row = MessageIndexState(
            message_id=msg.id, company_id=msg.company_id, status=status, reason=reason, chunk_id=chunk_id,
            last_error=error,
        )  # fmt: skip
        session.add(row)
        return
    state.status = status
    state.reason = reason
    state.last_error = error
    if chunk_id is not None or status is MessageIndexStatus.skipped:
        state.chunk_id = chunk_id
    state.attempts += 1

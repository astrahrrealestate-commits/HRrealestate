"""Core indexing engine for Message RAG.

Takes inbound and outbound messages, resolves metadata (person, unit, case),
groups them into conversational chunks with advisory locking, and computes embeddings.
"""

from uuid import UUID

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.contracts import Direction
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.enums import MessageIndexStatus
from app.db.models import (
    Case,
    CaseLink,
    ChannelIdentity,
    Lease,
    LeaseParty,
    MessageChunk,
    MessageIndexState,
    MessageRow,
    Person,
    UnderstandingRow,
    Unit,
)
from app.llm.embeddings import build_embedder
from app.tools.message_rag.chunker import (
    compute_content_hash,
    format_context_header,
    format_message_line,
    should_start_new_chunk,
)
from app.tools.message_rag.gate import should_index_message

log = get_logger(__name__)


def _resolve_outbound_person(session: Session, company_id: UUID, msg: MessageRow) -> UUID | None:
    """For outbound messages, attempt to resolve the recipient person_id."""
    # 1. Inherit from earlier inbound message in the same thread
    prior = session.scalar(
        select(MessageRow.person_id)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == msg.channel,
            MessageRow.thread_ref == msg.thread_ref,
            MessageRow.person_id.is_not(None),
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )
    if prior:
        return prior

    # 2. Look up recipient in channel_identities (from meta["to"])
    meta = msg.meta or {}
    to_list = meta.get("to") or []
    if isinstance(to_list, str):
        to_list = [to_list]

    for recipient in to_list:
        clean_target = str(recipient).strip().lower()
        person_id = session.scalar(
            select(ChannelIdentity.person_id).where(
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.identity == clean_target,
                ChannelIdentity.valid_to.is_(None),
            )
        )
        if person_id:
            return person_id

    return None


def _resolve_unit_and_lease(
    session: Session,
    company_id: UUID,
    person_id: UUID | None,
    case_id: UUID | None,
) -> tuple[UUID | None, UUID | None]:
    """Finds unit_id and lease_id from the case or the person's active lease."""
    # 1. From Case
    if case_id:
        case = session.get(Case, case_id)
        if case and case.unit_id:
            # Look up active lease for that unit
            lease_id = session.scalar(
                select(Lease.id)
                .where(Lease.company_id == company_id, Lease.unit_id == case.unit_id)
                .order_by(Lease.valid_from.desc())
                .limit(1)
            )
            return case.unit_id, lease_id

    # 2. From Person's Lease
    if person_id:
        row = session.execute(
            select(Lease.unit_id, Lease.id)
            .join(LeaseParty, LeaseParty.lease_id == Lease.id)
            .where(
                LeaseParty.company_id == company_id,
                LeaseParty.person_id == person_id,
            )
            .order_by(Lease.valid_from.desc())
            .limit(1)
        ).first()
        if row:
            return row[0], row[1]

    return None, None


def index_message(
    engine: Engine,
    settings: Settings,
    message_id: UUID,
) -> str:
    """Indexes a single message into Message RAG.

    Returns:
        "indexed" | "skipped" | "failed"
    """
    with Session(engine) as session:
        msg = session.get(MessageRow, message_id)
        if msg is None:
            return "failed"

        und = session.scalar(
            select(UnderstandingRow).where(
                UnderstandingRow.company_id == msg.company_id,
                UnderstandingRow.message_id == message_id,
            )
        )

        # Gate Check
        allowed, skip_reason = should_index_message(msg, und)
        if not allowed:
            _record_state(session, msg.company_id, message_id, MessageIndexStatus.skipped, reason=skip_reason)
            session.commit()
            return "skipped"

    # Transactional chunking & embedding under advisory lock
    with Session(engine) as session, session.begin():
        msg = session.get(MessageRow, message_id)
        if msg is None:
            return "failed"

        company_id = msg.company_id
        channel_str = msg.channel.value if hasattr(msg.channel, "value") else str(msg.channel)
        thread_ref = msg.thread_ref or msg.provider_msg_id

        # Advisory lock per thread to serialize chunk rebuilds
        lock_key = f"{company_id}:{channel_str}:{thread_ref}"
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": lock_key})

        # 1. Resolve Person
        person_id = msg.person_id
        if person_id is None and msg.direction is Direction.outbound:
            person_id = _resolve_outbound_person(session, company_id, msg)

        person_name: str | None = None
        if person_id:
            person_name = session.scalar(select(Person.display_name).where(Person.id == person_id))

        # 2. Resolve Case
        case_id = session.scalar(
            select(CaseLink.case_id).where(
                CaseLink.company_id == company_id,
                CaseLink.message_id == message_id,
            )
        )
        if case_id is None:
            # Inherit case from thread if already linked
            case_id = session.scalar(
                select(CaseLink.case_id)
                .join(MessageRow, MessageRow.id == CaseLink.message_id)
                .where(
                    MessageRow.company_id == company_id,
                    MessageRow.channel == msg.channel,
                    MessageRow.thread_ref == msg.thread_ref,
                )
                .limit(1)
            )

        case_summary = session.scalar(select(Case.summary).where(Case.id == case_id)) if case_id else None

        # 3. Resolve Unit & Lease
        unit_id, lease_id = _resolve_unit_and_lease(session, company_id, person_id, case_id)
        unit_address = session.scalar(select(Unit.address).where(Unit.id == unit_id)) if unit_id else None

        # 4. Resolve Subject
        meta = msg.meta or {}
        subject = meta.get("subject")

        # 5. Format Message Line
        new_line = format_message_line(msg, person_name)

        # 6. Locate open chunk for this thread
        open_chunk = session.scalar(
            select(MessageChunk)
            .where(
                MessageChunk.company_id == company_id,
                MessageChunk.channel == channel_str,
                MessageChunk.thread_ref == thread_ref,
                MessageChunk.is_open.is_(True),
            )
            .order_by(MessageChunk.last_sent_at.desc())
            .limit(1)
        )

        chunk: MessageChunk
        if open_chunk is not None:
            split_needed = should_start_new_chunk(
                len(open_chunk.text),
                len(new_line),
                open_chunk.last_sent_at,
                msg.sent_at,
                open_chunk.is_open,
            )
            if split_needed:
                open_chunk.is_open = False
                session.flush()
                chunk = _create_new_chunk(
                    company_id,
                    channel_str,
                    thread_ref,
                    msg,
                    new_line,
                    person_id,
                    person_name,
                    unit_id,
                    unit_address,
                    lease_id,
                    case_id,
                    case_summary,
                    subject,
                )
                session.add(chunk)
            else:
                chunk = open_chunk
                _append_to_chunk(
                    chunk,
                    msg,
                    new_line,
                    person_id,
                    person_name,
                    unit_id,
                    unit_address,
                    lease_id,
                    case_id,
                    case_summary,
                    subject,
                )
        else:
            chunk = _create_new_chunk(
                company_id,
                channel_str,
                thread_ref,
                msg,
                new_line,
                person_id,
                person_name,
                unit_id,
                unit_address,
                lease_id,
                case_id,
                case_summary,
                subject,
            )
            session.add(chunk)

        session.flush()

        # 7. Embed if content hash changed
        _embed_chunk_if_needed(chunk, settings)

        # 8. Record state
        _record_state(session, company_id, message_id, MessageIndexStatus.indexed, chunk_id=chunk.id)
        log.info("message_rag.indexed", message_id=str(message_id), chunk_id=str(chunk.id))

    return "indexed"


def _create_new_chunk(
    company_id: UUID,
    channel: str,
    thread_ref: str,
    msg: MessageRow,
    line: str,
    person_id: UUID | None,
    person_name: str | None,
    unit_id: UUID | None,
    unit_address: str | None,
    lease_id: UUID | None,
    case_id: UUID | None,
    case_summary: str | None,
    subject: str | None,
) -> MessageChunk:
    context = format_context_header(channel, thread_ref, subject, person_name, unit_address, case_summary)
    content_hash = compute_content_hash(context, line)

    is_outbound = msg.direction is Direction.outbound
    return MessageChunk(
        id=new_id(),
        company_id=company_id,
        channel=channel,
        thread_ref=thread_ref,
        message_ids=[msg.id],
        first_message_id=msg.id,
        last_message_id=msg.id,
        person_id=person_id,
        participant_ids=[person_id] if person_id else [],
        unit_id=unit_id,
        lease_id=lease_id,
        case_ids=[case_id] if case_id else [],
        has_inbound=not is_outbound,
        has_outbound=is_outbound,
        first_sent_at=msg.sent_at,
        last_sent_at=msg.sent_at,
        subject=subject,
        context=context,
        text=line,
        content_hash=content_hash,
        is_open=True,
    )


def _append_to_chunk(
    chunk: MessageChunk,
    msg: MessageRow,
    line: str,
    person_id: UUID | None,
    person_name: str | None,
    unit_id: UUID | None,
    unit_address: str | None,
    lease_id: UUID | None,
    case_id: UUID | None,
    case_summary: str | None,
    subject: str | None,
) -> None:
    if msg.id not in chunk.message_ids:
        chunk.message_ids = [*chunk.message_ids, msg.id]
    chunk.last_message_id = msg.id
    chunk.last_sent_at = max(chunk.last_sent_at, msg.sent_at)

    if person_id and person_id not in chunk.participant_ids:
        chunk.participant_ids = [*chunk.participant_ids, person_id]
    if person_id and not chunk.person_id:
        chunk.person_id = person_id

    if unit_id and not chunk.unit_id:
        chunk.unit_id = unit_id
    if lease_id and not chunk.lease_id:
        chunk.lease_id = lease_id

    if case_id and case_id not in chunk.case_ids:
        chunk.case_ids = [*chunk.case_ids, case_id]

    if msg.direction is Direction.outbound:
        chunk.has_outbound = True
    else:
        chunk.has_inbound = True

    chunk.text = f"{chunk.text}\n{line}"
    chunk.context = format_context_header(
        chunk.channel,
        chunk.thread_ref,
        subject or chunk.subject,
        person_name,
        unit_address,
        case_summary,
    )
    chunk.content_hash = compute_content_hash(chunk.context, chunk.text)


def _embed_chunk_if_needed(chunk: MessageChunk, settings: Settings) -> None:
    embedder = build_embedder(settings)
    text_to_embed = f"{chunk.context or ''}\n{chunk.text}"
    try:
        vector = embedder.embed_query(text_to_embed)
        chunk.embedding = vector
        chunk.embed_model = settings.embedding_model
        chunk.embed_dim = len(vector)
    except Exception as exc:
        log.warning("message_rag.embed_failed", error=str(exc), chunk_id=str(chunk.id))


def _record_state(
    session: Session,
    company_id: UUID,
    message_id: UUID,
    status: MessageIndexStatus,
    reason: str | None = None,
    chunk_id: UUID | None = None,
    error: str | None = None,
) -> None:
    state = session.get(MessageIndexState, message_id)
    if state is None:
        state = MessageIndexState(
            message_id=message_id,
            company_id=company_id,
            status=status,
            reason=reason,
            chunk_id=chunk_id,
            last_error=error,
        )
        session.add(state)
    else:
        state.status = status
        state.reason = reason
        if chunk_id is not None:
            state.chunk_id = chunk_id
        if error is not None:
            state.last_error = error
        state.attempts += 1

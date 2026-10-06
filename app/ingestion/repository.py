"""Ingestion persistence: raw events (+ atomic DBOS enqueue), normalised messages, attachments, delivery statuses.

Every write is idempotent through a per-company unique constraint (CLAUDE.md invariant 2) and every read is scoped
by `company_id` (invariant 4). Callers own the transaction: `record_event` enqueues inside it, so the row and its
workflow commit together (invariant 1). A per-message advisory lock serialises a message with its delivery statuses,
so a status arriving concurrently with its message is never lost.
"""

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import Channel, Message
from app.core.errors import NotFoundError, TenantMismatchError
from app.core.workflow_names import PIPELINE_QUEUE, PROCESS_EVENT, event_workflow_id
from app.db.enums import DeliveryStatus, RawEventStatus
from app.db.models import AttachmentRow, ChannelAccount, MessageRow, RawEvent
from app.ingestion.media import AttachmentInput

MAX_ERROR_CHARS = 2000
_STATUS_RANK = {DeliveryStatus.sent: 1, DeliveryStatus.delivered: 2, DeliveryStatus.read: 3, DeliveryStatus.failed: 4}


class Enqueuer(Protocol):
    """The slice of `dbos.DBOSClient` ingestion needs (kept narrow for fakes in unit tests)."""

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any: ...


def resolve_channel_account(session: Session, channel: Channel, address: str) -> ChannelAccount:
    match = (
        func.lower(ChannelAccount.address) == address.lower()  # mailboxes are case-insensitive
        if channel is Channel.gmail
        else ChannelAccount.address == address
    )
    account = session.scalar(select(ChannelAccount).where(ChannelAccount.channel == channel, match))
    if account is None:
        raise NotFoundError(f"no {channel.value} channel account for {address[:80]!r}")
    return account


def _lock_message(session: Session, company_id: UUID, channel: Channel, provider_msg_id: str) -> None:
    """Transaction-scoped lock on one provider message (its row and its status receipts)."""
    key = f"{company_id}:{channel.value}:{provider_msg_id}"
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def record_event(
    session: Session,
    client: Enqueuer,
    account: ChannelAccount,
    provider_msg_id: str,
    payload: dict[str, Any],
    *,
    status: RawEventStatus = RawEventStatus.pending,
    workflow: str | None = PROCESS_EVENT,
) -> UUID | None:
    """Insert-or-skip the raw event; when new and `workflow` is set, enqueue it in the same transaction.

    Returns the new raw event id, or None for a duplicate delivery to this company.
    """
    raw_id: UUID | None = session.scalar(
        insert(RawEvent)
        .values(
            company_id=account.company_id,
            provider=account.channel,
            provider_msg_id=provider_msg_id,
            payload=payload,
            status=status,
        )
        .on_conflict_do_nothing(index_elements=["company_id", "provider", "provider_msg_id"])
        .returning(RawEvent.id)
    )
    if raw_id is not None and workflow is not None:
        options = {"queue_name": PIPELINE_QUEUE, "workflow_name": workflow, "workflow_id": event_workflow_id(raw_id)}
        client.enqueue_in_transaction(session, options, str(raw_id))
    return raw_id


def get_raw_event(session: Session, company_id: UUID, raw_event_id: UUID, *, lock: bool = False) -> RawEvent:
    query = select(RawEvent).where(RawEvent.id == raw_event_id, RawEvent.company_id == company_id)
    raw = session.scalar(query.with_for_update() if lock else query)
    if raw is None:
        raise NotFoundError(f"raw event {raw_event_id}")
    return raw


def save_message(
    session: Session, message: Message, meta: dict[str, Any], attachments: list[AttachmentInput]
) -> tuple[UUID, bool]:
    """Persist a normalised message once per company. Returns (message id, created); retries get the existing id."""
    get_raw_event(session, message.company_id, message.raw_event_id)  # same company, or NotFoundError
    prefix = f"media/{message.company_id}/"
    if any(not att.s3_key.startswith(prefix) for att in attachments):
        raise TenantMismatchError("attachment stored under another company's prefix")
    _lock_message(session, message.company_id, message.channel, message.provider_msg_id)
    message_id: UUID | None = session.scalar(
        insert(MessageRow)
        .values(
            company_id=message.company_id,
            raw_event_id=message.raw_event_id,
            channel=message.channel,
            provider_msg_id=message.provider_msg_id,
            thread_ref=message.thread_ref,
            sender_identity=message.sender_identity,
            direction=message.direction,
            sent_at=message.sent_at,
            text=message.text,
            meta=meta,
        )
        .on_conflict_do_nothing(index_elements=["company_id", "channel", "provider_msg_id"])
        .returning(MessageRow.id)
    )
    if message_id is None:
        existing = session.scalar(
            select(MessageRow.id).where(
                MessageRow.company_id == message.company_id,
                MessageRow.channel == message.channel,
                MessageRow.provider_msg_id == message.provider_msg_id,
            )
        )
        if existing is None:  # pragma: no cover — conflict without a row would be a constraint bug
            raise NotFoundError(f"message {message.provider_msg_id}")
        return existing, False
    for att in attachments:
        session.add(
            AttachmentRow(
                company_id=message.company_id,
                message_id=message_id,
                s3_key=att.s3_key,
                mime_type=att.mime_type,
                filename=att.filename,
                size_bytes=att.size_bytes,
                sha256=att.sha256,
            )
        )
    if message.channel is Channel.whatsapp:
        _replay_statuses(session, message.company_id, message.provider_msg_id)
    session.flush()
    return message_id, True


def status_event_id(wamid: str, status: DeliveryStatus) -> str:
    return f"status:{wamid}:{status.value}"


def record_status(
    session: Session, account: ChannelAccount, wamid: str, status: DeliveryStatus, payload: dict[str, Any]
) -> bool:
    """Store a WhatsApp delivery receipt (audit) and apply it; serialised with the message by the advisory lock."""
    _lock_message(session, account.company_id, Channel.whatsapp, wamid)
    record_event(
        session,
        _NO_ENQUEUE,
        account,
        status_event_id(wamid, status),
        payload,
        status=RawEventStatus.ignored,
        workflow=None,
    )
    return apply_status(session, account.company_id, wamid, status)


def apply_status(session: Session, company_id: UUID, wamid: str, status: DeliveryStatus) -> bool:
    """Move a WhatsApp message's delivery status forward. False when the message is unknown or it would regress."""
    row = session.scalar(
        select(MessageRow)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.provider_msg_id == wamid,
        )
        .with_for_update()
    )
    if row is None:
        return False
    current = _STATUS_RANK[row.delivery_status] if row.delivery_status else 0
    if _STATUS_RANK[status] <= current:
        return False
    row.delivery_status = status
    session.flush()
    return True


def _replay_statuses(session: Session, company_id: UUID, wamid: str) -> None:
    """Statuses can arrive before their message: apply the best one already stored (exact ids, index lookup)."""
    candidates = {status_event_id(wamid, s): s for s in DeliveryStatus}
    seen = session.scalars(
        select(RawEvent.provider_msg_id).where(
            RawEvent.company_id == company_id,
            RawEvent.provider == Channel.whatsapp,
            RawEvent.provider_msg_id.in_(list(candidates)),
        )
    ).all()
    if seen:
        session.flush()
        apply_status(session, company_id, wamid, max((candidates[s] for s in seen), key=_STATUS_RANK.__getitem__))


def mark_raw_event(
    session: Session, company_id: UUID, raw_event_id: UUID, status: RawEventStatus, error: str | None = None
) -> None:
    raw = get_raw_event(session, company_id, raw_event_id, lock=True)
    raw.status = status
    raw.attempts += 1
    raw.last_error = error[:MAX_ERROR_CHARS] if error else None
    session.flush()


class _NoEnqueue:
    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("status receipts never enqueue work")


_NO_ENQUEUE = _NoEnqueue()

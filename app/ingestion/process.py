"""Event processing (no DBOS here): raw event → normalised Message → storage + rows; Gmail history sync; watches.

Functions raise only *transient* errors (retried by the calling DBOS step). Data problems are recorded on the raw
event (`failed` / `ignored`) and returned as outcomes, never retried. Errors that outlive the step retries, and
unexpected ones (bugs), are recorded as `failed` with the `requeue:` marker; the hourly requeue sweep reruns them up
to MAX_REQUEUES times, and also reruns events stranded in `pending` (e.g. a deploy during a provider outage).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.channels.gmail.google import GmailApiError
from app.channels.gmail.inbound import to_message as gmail_to_message
from app.channels.gmail.ports import GmailMailbox, HistoryExpiredError
from app.channels.whatsapp import inbound as wa
from app.channels.whatsapp.media import WhatsAppMedia, WhatsAppMediaError
from app.contracts import Channel, Direction, Message
from app.core.errors import IgnoredMessageError, NotFoundError, UnroutableMessageError
from app.core.ids import new_id
from app.core.logging import get_logger
from app.core.workflow_names import event_workflow_id, stale_event_workflow_id
from app.db.enums import RawEventStatus
from app.db.models import ChannelAccount, GmailSyncState, MessageRow, OwnerAccount, RawEvent
from app.ingestion.media import AttachmentInput, store_attachment
from app.ingestion.repository import Enqueuer, mark_raw_event, record_event, save_message
from app.storage.ports import ObjectStorage

log = get_logger(__name__)
RESYNC_WINDOW = timedelta(days=7)  # expired history cursor: bounded catch-up
FIRST_SYNC_WINDOW = timedelta(days=1)  # mailbox without a cursor (watch never ran): recent mail only, no flood
REQUEUE_PREFIX = "requeue:"  # last_error marker for failures worth reprocessing (outlived retries, or a bug fixed)
MAX_REQUEUES = 5
STALE_PENDING_AFTER = timedelta(hours=1)  # > the step retry budget (~10 min) plus queue backlog headroom
STALE_PENDING_UNTIL = timedelta(days=7)  # older stragglers need a human (`make workflows`)


@dataclass
class IngestDeps:
    engine: Engine
    storage: ObjectStorage
    enqueuer: Enqueuer
    gmail_mailbox: Callable[[str], GmailMailbox]
    whatsapp_media: Callable[[str], WhatsAppMedia]
    gmail_topic: str


@dataclass(frozen=True)
class Persisted:
    outcome: str  # processed | duplicate | failed | ignored
    message_id: str | None = None
    route: str = "none"  # owner | pipeline | none


def is_transient(exc: BaseException) -> bool:
    """Errors worth retrying: infrastructure and provider hiccups, never data problems."""
    if isinstance(exc, OperationalError | httpx.TransportError | OSError):  # OSError: sockets, timeouts, disk
        return True
    if isinstance(exc, WhatsAppMediaError | GmailApiError):
        return exc.retryable
    return False


# ---- process_event -----------------------------------------------------------------------------------------------


def persist_event(deps: IngestDeps, raw_event_id: UUID) -> Persisted:
    with Session(deps.engine) as session:
        raw = session.get(RawEvent, raw_event_id)  # id comes from our own enqueue; everything after is company-scoped
        if raw is None:
            return Persisted("failed")
        if not _runnable(raw):
            return _already(session, raw)
        company_id, provider, payload = raw.company_id, raw.provider, dict(raw.payload)
    try:
        message, meta, attachments = _normalise(deps, company_id, raw_event_id, provider, payload)
    except IgnoredMessageError as exc:
        return _finish(deps, company_id, raw_event_id, RawEventStatus.ignored, str(exc))
    except (UnroutableMessageError, NotFoundError, ValueError) as exc:
        return _finish(deps, company_id, raw_event_id, RawEventStatus.failed, f"{type(exc).__name__}: {exc}")
    with Session(deps.engine) as session, session.begin():
        message_id, _ = save_message(session, message, meta, attachments)
        mark_raw_event(session, company_id, raw_event_id, RawEventStatus.processed)
        route = _route(session, message)
    return Persisted("processed", str(message_id), route)


def _runnable(raw: RawEvent) -> bool:
    """Pending, or failed retryably and requeued. Everything else already reached a final state."""
    if raw.status is RawEventStatus.pending:
        return True
    return raw.status is RawEventStatus.failed and (raw.last_error or "").startswith(REQUEUE_PREFIX)


def mark_requeueable(deps: IngestDeps, raw_event_id: UUID, error: str) -> None:
    """Record a failure that outlived its retries (or an unexpected bug) so the requeue sweep picks it up."""
    with Session(deps.engine) as session, session.begin():
        raw = session.get(RawEvent, raw_event_id)
        if raw is not None and _runnable(raw):
            mark_raw_event(session, raw.company_id, raw.id, RawEventStatus.failed, f"{REQUEUE_PREFIX} {error}")


def _already(session: Session, raw: RawEvent) -> Persisted:
    """Retried after the work committed: return the same routing so the child enqueue is replayed idempotently."""
    row = session.scalar(
        select(MessageRow).where(MessageRow.company_id == raw.company_id, MessageRow.raw_event_id == raw.id)
    )
    if row is None:
        return Persisted(raw.status.value)
    message = Message(
        channel=row.channel,
        provider_msg_id=row.provider_msg_id,
        thread_ref=row.thread_ref,
        sender_identity=row.sender_identity,
        direction=row.direction,
        sent_at=row.sent_at,
        text=row.text,
        raw_event_id=raw.id,
        company_id=raw.company_id,
    )
    return Persisted("duplicate", str(row.id), _route(session, message))


def _finish(deps: IngestDeps, company_id: UUID, raw_event_id: UUID, status: RawEventStatus, why: str) -> Persisted:
    with Session(deps.engine) as session, session.begin():
        mark_raw_event(session, company_id, raw_event_id, status, why)
    log.info("ingest.event_not_processed", raw_event_id=str(raw_event_id), status=status.value)
    return Persisted(status.value)


def _normalise(
    deps: IngestDeps, company_id: UUID, raw_event_id: UUID, provider: Channel, payload: dict[str, Any]
) -> tuple[Message, dict[str, Any], list[AttachmentInput]]:
    if provider is Channel.whatsapp:
        return _normalise_whatsapp(deps, company_id, raw_event_id, payload)
    mailbox = deps.gmail_mailbox(str(payload["mailbox"]))
    gm = mailbox.get_message(str(payload["message_id"]))  # NotFoundError: deleted since the push
    message, meta, parts = gmail_to_message(
        gm, company_id=company_id, raw_event_id=raw_event_id, mailbox=str(payload["mailbox"])
    )
    stored = [store_attachment(deps.storage, company_id, p.data, p.mime_type, p.filename) for p in parts]
    return message, meta, stored


def _normalise_whatsapp(
    deps: IngestDeps, company_id: UUID, raw_event_id: UUID, payload: dict[str, Any]
) -> tuple[Message, dict[str, Any], list[AttachmentInput]]:
    event = wa.event_from_payload(payload)
    if event is None:
        raise ValueError("unreadable whatsapp payload")
    message, meta = wa.to_message(event, company_id=company_id, raw_event_id=raw_event_id)
    if event.media is None:
        return message, meta, []
    try:
        blob = deps.whatsapp_media(event.phone_number_id).download(event.media.id)
    except (NotFoundError, WhatsAppMediaError) as exc:
        if isinstance(exc, WhatsAppMediaError) and exc.retryable:
            raise
        return message, {**meta, "media_error": type(exc).__name__}, []  # keep the message, flag the media
    stored = store_attachment(deps.storage, company_id, blob.data, blob.mime_type, event.media.filename)
    return message, meta, [stored]


def _route(session: Session, message: Message) -> str:
    """Owner commands come only over WhatsApp, where the sender id is provider-verified. An email From: header is
    trivially spoofable, so Gmail never routes to the owner handler in Phase 1."""
    if message.direction is Direction.outbound:
        return "none"
    if message.channel is not Channel.whatsapp:
        return "pipeline"
    owner = session.scalar(
        select(OwnerAccount.id).where(
            OwnerAccount.company_id == message.company_id, OwnerAccount.whatsapp_e164 == message.sender_identity
        )
    )
    return "owner" if owner is not None else "pipeline"


def requeue_candidates(deps: IngestDeps) -> list[tuple[UUID, str]]:
    """(raw event id, workflow id) to rerun: retryable failures, and events stranded in `pending` (system cron,
    all companies). A rerun racing a late original is safe: persisting a message is idempotent and locked."""
    now = datetime.now(UTC)
    with Session(deps.engine) as session:
        failed = session.execute(
            select(RawEvent.id, RawEvent.attempts).where(
                RawEvent.status == RawEventStatus.failed,
                RawEvent.last_error.startswith(REQUEUE_PREFIX, autoescape=True),
                RawEvent.attempts < MAX_REQUEUES,
            )
        ).all()
        stranded = session.scalars(
            select(RawEvent.id).where(
                RawEvent.status == RawEventStatus.pending,
                RawEvent.received_at < now - STALE_PENDING_AFTER,
                RawEvent.received_at > now - STALE_PENDING_UNTIL,
            )
        ).all()
    reruns = [(r.id, event_workflow_id(r.id, r.attempts)) for r in failed]
    return reruns + [(raw_id, stale_event_workflow_id(raw_id, now)) for raw_id in stranded]


# ---- gmail_sync --------------------------------------------------------------------------------------------------


def sync_mailbox(deps: IngestDeps, account_id: UUID, push_history_id: int) -> int:
    """Record one raw event per new Gmail message and advance the cursor.

    Gmail is read with no transaction open; the write is one short transaction that re-checks the cursor
    (compare-and-swap). The gmail_sync queue runs one sync at a time, so the swap only guards odd interleavings.
    """
    with Session(deps.engine) as session:
        account = session.get(ChannelAccount, account_id)
        if account is None or account.channel is not Channel.gmail:
            return 0
        company_id, address = account.company_id, account.address
        cursor = _cursor(session, company_id, account_id)
    if cursor is not None and push_history_id <= cursor:
        return 0  # stale or duplicate notification
    mailbox = deps.gmail_mailbox(address)
    ids, latest = _new_message_ids(mailbox, cursor)
    with Session(deps.engine) as session, session.begin():
        _ensure_state(session, company_id, account_id)
        state = _locked_state(session, company_id, account_id)
        current = int(state.history_id) if state.history_id else None
        if current != cursor:
            log.info("gmail.sync.cursor_moved", account_id=str(account_id))
            return 0  # another sync committed meanwhile and covered this range
        account = session.get(ChannelAccount, account_id)
        if account is None:
            raise NotFoundError(f"gmail account {account_id} removed during sync")
        base = {"v": 1, "kind": "gmail", "mailbox": address}
        new = [record_event(session, deps.enqueuer, account, mid, {**base, "message_id": mid}) for mid in ids]
        recorded = sum(raw_id is not None for raw_id in new)
        state.history_id = str(max(latest, push_history_id))
    log.info("gmail.sync", account_id=str(account_id), new=recorded)
    return recorded


def _cursor(session: Session, company_id: UUID, account_id: UUID) -> int | None:
    value = session.scalar(
        select(GmailSyncState.history_id).where(
            GmailSyncState.company_id == company_id, GmailSyncState.channel_account_id == account_id
        )
    )
    return int(value) if value else None


def _ensure_state(session: Session, company_id: UUID, account_id: UUID) -> None:
    """Upsert the cursor row so concurrent first syncs / watch renewals never collide on insert."""
    session.execute(
        insert(GmailSyncState)
        .values(id=new_id(), company_id=company_id, channel_account_id=account_id)
        .on_conflict_do_nothing(index_elements=["channel_account_id"])
    )


def _locked_state(session: Session, company_id: UUID, account_id: UUID) -> GmailSyncState:
    state = session.scalar(
        select(GmailSyncState)
        .where(GmailSyncState.company_id == company_id, GmailSyncState.channel_account_id == account_id)
        .with_for_update()
    )
    if state is None:  # pragma: no cover — _ensure_state just inserted it
        raise NotFoundError(f"gmail sync state for {account_id}")
    return state


def _new_message_ids(mailbox: GmailMailbox, start: int | None) -> tuple[list[str], int]:
    if start is not None:
        try:
            ids: list[str] = []
            token: str | None = None
            while True:
                page = mailbox.history_since(start, page_token=token)
                ids += [i for i in page.message_ids if i not in ids]
                if not page.next_page_token:
                    return ids, page.history_id
                token = page.next_page_token
        except HistoryExpiredError:
            log.warning("gmail.history_expired_resync", start=start)
            return mailbox.message_ids_since(datetime.now(UTC) - RESYNC_WINDOW), mailbox.current_history_id()
    # first sync without a cursor: recent mail only (dedupe makes already-known messages no-ops)
    return mailbox.message_ids_since(datetime.now(UTC) - FIRST_SYNC_WINDOW), mailbox.current_history_id()


# ---- watches / backfill ------------------------------------------------------------------------------------------


def gmail_accounts(deps: IngestDeps) -> list[tuple[UUID, str, UUID]]:
    """All Gmail accounts across companies — a deliberate cross-tenant read for system crons (watch, backfill)."""
    with Session(deps.engine) as session:
        rows = session.execute(
            select(ChannelAccount.id, ChannelAccount.address, ChannelAccount.company_id).where(
                ChannelAccount.channel == Channel.gmail
            )
        ).all()
    return [(r.id, r.address, r.company_id) for r in rows]


def renew_watch(deps: IngestDeps, account_id: UUID, address: str, company_id: UUID) -> datetime:
    result = deps.gmail_mailbox(address).watch(deps.gmail_topic)
    with Session(deps.engine) as session, session.begin():
        _ensure_state(session, company_id, account_id)  # may race a first sync: upsert, never a plain insert
        state = _locked_state(session, company_id, account_id)
        if not state.history_id:  # onboarding: syncs start from "now", no historic flood
            state.history_id = str(result.history_id)
        state.watch_expires_at = result.expiration
    return result.expiration

"""Event processing (no DBOS here): raw event → normalised Message → storage + rows → routing; requeue candidates.

Gmail mailbox sync lives in app.ingestion.gmail_sync.

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
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.channels.gmail.google import GmailApiError
from app.channels.gmail.inbound import to_message as gmail_to_message
from app.channels.gmail.ports import GmailMailbox
from app.channels.whatsapp import inbound as wa
from app.channels.whatsapp import normalise as wa_normalise
from app.channels.whatsapp.media import WhatsAppMedia, WhatsAppMediaError
from app.context.message_origin import mailbox_addresses, owner_emails
from app.contracts import Channel, Direction, Message
from app.core.errors import IgnoredMessageError, NotFoundError, UnroutableMessageError, UnsafeConfigurationError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import requeue_workflow_id, stale_event_workflow_id
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.known_contacts import feeds_pipeline, is_known_contact
from app.db.models import MessageRow, OwnerAccount, RawEvent
from app.ingestion.media import AttachmentInput, store_attachment
from app.ingestion.repository import Enqueuer, mark_raw_event, save_message
from app.storage.ports import ObjectStorage
from app.tools.message_rag import index_message

log = get_logger(__name__)
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
        last_attempt = raw.attempts >= MAX_REQUEUES - 1  # no rerun follows: give up on media, keep the message
    try:
        message, meta, attachments = _normalise(deps, company_id, raw_event_id, provider, payload, last_attempt)
    except IgnoredMessageError as exc:
        return _finish(deps, company_id, raw_event_id, RawEventStatus.ignored, str(exc))
    except (UnroutableMessageError, NotFoundError, ValueError) as exc:
        return _finish(deps, company_id, raw_event_id, RawEventStatus.failed, f"{type(exc).__name__}: {exc}")
    with Session(deps.engine) as session, session.begin():
        message_id, _ = save_message(session, message, meta, attachments)
        mark_raw_event(session, company_id, raw_event_id, RawEventStatus.processed)

        route = _route(session, message, message_id)
    _index_outbound(deps, message, message_id)
    return Persisted("processed", str(message_id), route)


def _index_outbound(deps: IngestDeps, message: Message, message_id: UUID) -> None:
    """Outbound mail and WhatsApp feed the Super Agent's message search. After commit, best effort: a failed embed must
    never fail ingestion (the backfill job catches up)."""
    if message.direction is not Direction.outbound:
        return
    try:
        index_message(deps.engine, get_settings(), message_id)
    except Exception as exc:  # search indexing is optional; ingestion has already committed
        log.warning("ingest.outbound_index_failed", error=str(exc), message_id=str(message_id))


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
            if raw.attempts >= MAX_REQUEUES:  # no rerun follows: a human must look (docs/go-live-channels.md)
                log.error("ingest.requeue_exhausted", raw_event_id=str(raw.id), attempts=raw.attempts)


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
    return Persisted("duplicate", str(row.id), _route(session, message, row.id))


def _finish(deps: IngestDeps, company_id: UUID, raw_event_id: UUID, status: RawEventStatus, why: str) -> Persisted:
    with Session(deps.engine) as session, session.begin():
        mark_raw_event(session, company_id, raw_event_id, status, why)
    log.info("ingest.event_not_processed", raw_event_id=str(raw_event_id), status=status.value)
    return Persisted(status.value)


def _normalise(
    deps: IngestDeps,
    company_id: UUID,
    raw_event_id: UUID,
    provider: Channel,
    payload: dict[str, Any],
    last_attempt: bool = False,
) -> tuple[Message, dict[str, Any], list[AttachmentInput]]:
    if provider is Channel.whatsapp:
        return _normalise_whatsapp(deps, company_id, raw_event_id, payload, last_attempt)
    if provider is Channel.google_chat:
        return _normalise_google_chat(company_id, raw_event_id, payload)
    mailbox = deps.gmail_mailbox(str(payload["mailbox"]))
    gm = mailbox.get_message(str(payload["message_id"]))  # NotFoundError: deleted since the push
    owners = owner_addresses(deps.engine, company_id)
    message, meta, parts = gmail_to_message(
        gm,
        company_id=company_id,
        raw_event_id=raw_event_id,
        mailbox=str(payload["mailbox"]),
        forwarders=owners,
        own_addresses=company_mailboxes(deps.engine, company_id),
    )
    if message.direction is Direction.inbound and message.sender_identity.lower() in owners:
        meta = {**meta, "owner_authored": True}  # Harjot's own mail, copied in: context, never drafted to
    stored = [store_attachment(deps.storage, company_id, p.data, p.mime_type, p.filename) for p in parts]
    return message, meta, stored


def owner_addresses(engine: Engine, company_id: UUID) -> frozenset[str]:
    """Addresses Harjot's team mails from (owner account, whitelisted users, configured owner email): a mail sent
    from one of these that forwards a tenant's mail is attributed to the tenant, not to them."""
    with Session(engine) as session:
        return owner_emails(session, company_id)


def company_mailboxes(engine: Engine, company_id: UUID) -> frozenset[str]:
    """Every mailbox the company has connected: a Reply-To naming one of them is not the person who wrote."""
    with Session(engine) as session:
        return mailbox_addresses(session, company_id)


def _normalise_google_chat(
    company_id: UUID, raw_event_id: UUID, payload: dict[str, Any]
) -> tuple[Message, dict[str, Any], list[AttachmentInput]]:
    from app.channels.google_chat.inbound import parse_chat_event
    from app.channels.google_chat.inbound import to_message as chat_to_message

    event = parse_chat_event(payload)
    message, meta = chat_to_message(event, company_id=company_id, raw_event_id=raw_event_id)
    return message, meta, []


def _normalise_whatsapp(
    deps: IngestDeps, company_id: UUID, raw_event_id: UUID, payload: dict[str, Any], last_attempt: bool
) -> tuple[Message, dict[str, Any], list[AttachmentInput]]:
    event = wa.event_from_payload(payload)
    if event is None:
        raise ValueError("unreadable whatsapp payload")
    message, meta = wa_normalise.to_message(event, company_id=company_id, raw_event_id=raw_event_id)
    if event.media is None:
        return message, meta, []
    try:
        blob = deps.whatsapp_media(event.phone_number_id).download(event.media.id)
    except (NotFoundError, WhatsAppMediaError, UnsafeConfigurationError) as exc:
        if isinstance(exc, WhatsAppMediaError) and exc.retryable and not last_attempt:
            raise
        log.error("ingest.media_not_stored", raw_event_id=str(raw_event_id), error_type=type(exc).__name__)
        return message, {**meta, "media_error": type(exc).__name__}, []  # keep the message, flag the media
    stored = store_attachment(deps.storage, company_id, blob.data, blob.mime_type, event.media.filename)
    return message, meta, [stored]


def _route(session: Session, message: Message, message_id: UUID) -> str:
    """Owner commands come only over WhatsApp and Google Chat, where the sender id is provider-verified.
    An email From: header is trivially spoofable, so Gmail never routes to the owner handler in Phase 1.
    WhatsApp from a number the directory does not know stays in Chats and never reaches the pipeline (ADR 0015)."""
    if message.direction is Direction.outbound:
        if message.channel is Channel.whatsapp:
            _skip_echo_to_stranger(session, message, message_id)
        return "none"
    if message.channel is Channel.google_chat:
        owner = session.scalar(
            select(OwnerAccount.id).where(
                OwnerAccount.company_id == message.company_id,
                OwnerAccount.chat_user == message.sender_identity,
            )
        )
        return "owner" if owner is not None else "none"
    if message.channel is not Channel.whatsapp:
        return "pipeline"
    owner = session.scalar(
        select(OwnerAccount.id).where(
            OwnerAccount.company_id == message.company_id, OwnerAccount.whatsapp_e164 == message.sender_identity
        )
    )
    if owner is not None:
        return "owner"
    return "pipeline" if _is_pipeline_contact(session, message, message_id) else "none"


def _skip_echo_to_stranger(session: Session, message: Message, message_id: UUID) -> None:
    """A reply Harjot typed on his phone to a chat-only chat stays out of the case world with that chat."""
    row = session.get(MessageRow, message_id)
    if row is None or row.pipeline_status is not PipelineStatus.pending or message.thread_ref is None:
        return
    if not feeds_pipeline(session, message.company_id, message.channel, message.thread_ref):
        row.pipeline_status = PipelineStatus.skipped


def _is_pipeline_contact(session: Session, message: Message, message_id: UUID) -> bool:
    """The webhook decided once and marked the row `skipped`; a row the worker created itself is decided here."""
    row = session.get(MessageRow, message_id)
    if row is None or row.pipeline_status is PipelineStatus.skipped:
        return False
    if row.pipeline_status is not PipelineStatus.pending:  # a replay after the pipeline already ran
        return True
    if is_known_contact(session, message.company_id, message.channel, message.sender_identity):
        return True
    row.pipeline_status = PipelineStatus.skipped
    return False


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
    reruns = [(r.id, requeue_workflow_id(r.id, r.attempts, now)) for r in failed]
    return reruns + [(raw_id, stale_event_workflow_id(raw_id, now)) for raw_id in stranded]

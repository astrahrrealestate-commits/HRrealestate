"""Owner-typed sends from the Chats page (ADR 0013): store the pending outbound row, then enqueue `chat.send_message`.

The API never sends: it commits a `messages` row (`delivery_status` NULL, shown as pending) and enqueues the workflow by
name; the sender owns every gate. The row is deduped on `meta->>'client_msg_id'` (never on `provider_msg_id`: the
sender swaps the placeholder for the wamid), so a repeated POST returns the same row and re-enqueues the same
deterministic workflow id, which also heals a POST whose enqueue was lost.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.chats.composer import composer_state, is_own_number
from app.api.chats.routes import NOT_FOUND, ChatNotFoundError, to_message
from app.api.chats.schemas import ChatMessage, SendChatMessageRequest, SuggestionsOut
from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.v1.auth import Principal, require_session
from app.api.v1.enqueue import enqueue_chat_send
from app.api.v1.session_limits import chat_send_limit
from app.contracts import Channel, Direction
from app.core.logging import get_logger
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.models import Company
from app.db.models.ingestion import MessageRow, RawEvent
from app.pipeline import chat_repo

send_router = APIRouter()
log = get_logger(__name__)
DASHBOARD = "dashboard"
DUPLICATE_CHAT = "client message id already used in another chat"
TEXT_CHANGED = "client message id already used with different text"
BAD_SUGGESTION = "suggestion is not an open reply draft of this chat"


class ClientIdReusedError(Exception):
    """The same `client_msg_id` already names a message of a different chat."""


class ClientTextChangedError(Exception):
    """The same `client_msg_id` already names a message with other text."""


class ComposerClosedError(Exception):
    def __init__(self, state: str) -> None:
        super().__init__(state)
        self.state = state


class SuggestionInvalidError(Exception):
    """`suggestion_action_id` is not the chat's own open reply draft."""


def find_by_client_id(session: Session, company_id: UUID, client_msg_id: str) -> MessageRow | None:
    stmt = select(MessageRow).where(
        MessageRow.company_id == company_id,
        MessageRow.channel == Channel.whatsapp,
        MessageRow.direction == Direction.outbound,
        MessageRow.meta["client_msg_id"].as_string() == client_msg_id,
    )
    return session.scalars(stmt).first()


def _meta(client_msg_id: UUID, suggestion_id: UUID | None) -> dict[str, object]:
    meta: dict[str, object] = {"client_msg_id": str(client_msg_id), "type": "text", "dashboard": True}
    if suggestion_id is not None:
        meta["suggestion_action_id"] = str(suggestion_id)
    return meta


def insert_pending(
    session: Session,
    company_id: UUID,
    chat_key: str,
    client_msg_id: UUID,
    text: str,
    suggestion_id: UUID | None,
    now: datetime,
) -> MessageRow:
    """The processed raw event and the outbound row, flushed in the caller's transaction."""
    placeholder = f"dash:{client_msg_id}"
    raw = RawEvent(
        company_id=company_id,
        provider=Channel.whatsapp,
        provider_msg_id=placeholder,
        payload={"kind": "dashboard_send"},
        status=RawEventStatus.processed,
    )
    session.add(raw)
    session.flush()
    row = MessageRow(
        company_id=company_id,
        raw_event_id=raw.id,
        channel=Channel.whatsapp,
        provider_msg_id=placeholder,
        thread_ref=chat_key,
        sender_identity=DASHBOARD,
        direction=Direction.outbound,
        sent_at=now,
        text=text,
        delivery_status=None,
        meta=_meta(client_msg_id, suggestion_id),
        pipeline_status=PipelineStatus.done,  # the pipeline runs on inbound messages only
    )
    session.add(row)
    session.flush()
    return row


def _replay(row: MessageRow, chat_key: str, req: SendChatMessageRequest) -> ChatMessage:
    """The stored row of an earlier POST with this `client_msg_id`, if it really is the same message."""
    if row.thread_ref != chat_key:
        raise ClientIdReusedError
    if row.text != req.text:
        raise ClientTextChangedError
    return to_message(row, [], (False, None), None)


def _check_new(session: Session, company_id: UUID, chat_key: str, req: SendChatMessageRequest, now: datetime) -> None:
    """A new message needs a chat we may answer, an open composer and (if named) the chat's own open suggestion."""
    inbound = chat_repo.latest_inbound(session, company_id, chat_key)
    if inbound is None or is_own_number(session, company_id, chat_key):
        raise ChatNotFoundError  # a number that never wrote to us, or one of our own, is not a chat we may answer
    state = composer_state(session.get(Company, company_id), inbound, now).state
    if state != "open":
        raise ComposerClosedError(state)
    if req.suggestion_action_id is not None:
        own, _ = chat_repo.suggestions(session, company_id, chat_key)
        if own != req.suggestion_action_id:
            raise SuggestionInvalidError


def _store_once(
    engine: Engine, company_id: UUID, chat_key: str, req: SendChatMessageRequest, now: datetime
) -> ChatMessage:
    with Session(engine) as session, session.begin():
        existing = find_by_client_id(session, company_id, str(req.client_msg_id))
        if existing is not None:  # a replay is answered before any gate: the first POST already passed them
            return _replay(existing, chat_key, req)
        _check_new(session, company_id, chat_key, req, now)
        row = insert_pending(session, company_id, chat_key, req.client_msg_id, req.text, req.suggestion_action_id, now)
        return to_message(row, [], (False, None), None)


def _store(engine: Engine, company_id: UUID, key: str, req: SendChatMessageRequest, now: datetime) -> ChatMessage:
    chat_key = chat_repo.parse_chat_key(key)
    try:
        return _store_once(engine, company_id, chat_key, req, now)
    except IntegrityError:  # a twin POST won the unique index between our lookup and insert: answer from its row
        with Session(engine) as session:
            winner = find_by_client_id(session, company_id, str(req.client_msg_id))
            if winner is None:
                raise
            return _replay(winner, chat_key, req)


def _enqueue(client: WorkflowClient, company_id: UUID, client_msg_id: UUID, message_id: UUID) -> None:
    """The row is committed, so a failed enqueue is not a failed send: the owner's re-POST (same id) enqueues again."""
    try:
        enqueue_chat_send(client, company_id, client_msg_id, message_id)
    except Exception as exc:  # any queue or database error: the pending row stays and the re-POST recovers
        log.warning("chats.enqueue_failed", error_type=type(exc).__name__, message_id=str(message_id))


@send_router.post("/{chat_key}/messages", status_code=202, dependencies=[Depends(chat_send_limit)])
async def send_message(
    chat_key: str,
    body: SendChatMessageRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
    principal: Annotated[Principal, Depends(require_session)],
) -> ChatMessage:
    try:
        message = await run_in_threadpool(_store, engine, principal.company_id, chat_key, body, datetime.now(UTC))
    except (chat_repo.BadChatKeyError, ChatNotFoundError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    except SuggestionInvalidError:
        raise HTTPException(status_code=422, detail=BAD_SUGGESTION) from None
    except ClientIdReusedError:
        raise HTTPException(status_code=409, detail=DUPLICATE_CHAT) from None
    except ClientTextChangedError:
        raise HTTPException(status_code=409, detail=TEXT_CHANGED) from None
    except ComposerClosedError as closed:
        raise HTTPException(status_code=409, detail=f"cannot send: {closed.state}") from None
    await run_in_threadpool(_enqueue, client, principal.company_id, body.client_msg_id, message.id)
    log.info("chats.send_stored", message_id=str(message.id))
    return message


def _read_suggestions(engine: Engine, company_id: UUID, key: str) -> SuggestionsOut:
    chat_key = chat_repo.parse_chat_key(key)
    with Session(engine) as session:
        if not chat_repo.chat_messages(session, company_id, chat_key, before=None, limit=1):
            raise ChatNotFoundError
        action_id, variants = chat_repo.suggestions(session, company_id, chat_key)
    return SuggestionsOut(action_id=action_id, variants=variants)


@send_router.get("/{chat_key}/suggestions")
async def get_suggestions(
    chat_key: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> SuggestionsOut:
    try:
        return await run_in_threadpool(_read_suggestions, engine, principal.company_id, chat_key)
    except (chat_repo.BadChatKeyError, ChatNotFoundError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None

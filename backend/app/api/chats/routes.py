"""Chats read API: the chat list, one chat's messages, and the read marker. Cookie session, `inbox` section."""

import urllib.parse
from collections import defaultdict
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.chats.schemas import ChatItem, ChatMessage, ChatQuote, ChatThread
from app.api.deps import get_engine, get_storage
from app.api.inbox.routes import INLINE_TYPES
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.schemas import AttachmentOut
from app.core.logging import get_logger
from app.db.models.ingestion import AttachmentRow, MessageRow
from app.pipeline import chat_repo
from app.pipeline.read_repo import (
    MAX_PAGE,
    MAX_THREAD_MESSAGES,
    BadCursorError,
    attachments_for,
    parse_cursor,
    suspicious_flags,
)
from app.storage.ports import MAX_PRESIGN_TTL_S, ObjectStorage

router = APIRouter(prefix="/api/chats", tags=["chats"], dependencies=[Depends(require_section("inbox"))])
log = get_logger(__name__)
NOT_FOUND = "chat not found"  # one body for malformed, unknown and foreign keys: nothing to tell them apart
MAX_QUERY_LEN = 100
MAX_ERROR_LEN = 200  # a provider error text can be long; the owner sees a short reason


class ChatNotFoundError(Exception):
    """Raised inside the threadpool work; the route turns it into the one 404."""


def _read_list(
    engine: Engine, company_id: UUID, before: str | None, limit: int, flt: chat_repo.ChatFilter, q: str | None
) -> list[ChatItem]:
    cursor = parse_cursor(before) if before else None
    with Session(engine) as session:
        chats = chat_repo.chat_list(
            session, company_id, before=cursor, limit=limit, filter=flt, q=(q or "").strip() or None
        )
    return [ChatItem(**vars(c), cursor=f"{c.last_at.isoformat()}|{c.last_message_id}") for c in chats]


def _attachment(a: AttachmentRow, storage: ObjectStorage) -> AttachmentOut:
    """Only the image and PDF types a browser can show without running anything are served inline; everything else
    (html, svg, xml, unknown) is forced to an opaque download, whatever the sender claimed."""
    mime = (a.mime_type or "").split(";")[0].strip().lower()
    inline = mime in INLINE_TYPES
    filename = urllib.parse.quote(a.filename or "attachment", safe="")
    disposition = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{filename}"
    return AttachmentOut(
        id=a.id,
        filename=a.filename,
        mime_type=a.mime_type,
        size_bytes=a.size_bytes,
        url=storage.presigned_url(
            a.s3_key,
            MAX_PRESIGN_TTL_S,
            content_type=mime if inline else "application/octet-stream",
            disposition=disposition,
        ),
    )


def _to_message(
    m: MessageRow,
    atts: list[AttachmentOut],
    flag: tuple[bool, str | None],
    quoted: MessageRow | None,
) -> ChatMessage:
    error = m.meta.get("send_error")
    return ChatMessage(
        id=m.id,
        direction=m.direction,
        sent_at=m.sent_at,
        text=m.text,
        kind=m.meta.get("type"),
        delivery_status=m.delivery_status,
        error=str(error)[:MAX_ERROR_LEN] if error else None,
        suspicious=flag[0],
        suspicious_reason=flag[1],
        reply_to=ChatQuote(id=quoted.id, text=quoted.text) if quoted is not None else None,
        attachments=atts,
        pending=chat_repo.is_pending_send(m.direction, m.delivery_status, m.meta),
    )


def _quote_of(m: MessageRow, quoted: dict[str, MessageRow]) -> MessageRow | None:
    ref = m.meta.get("reply_to")
    return quoted.get(str(ref)) if ref else None


def _read_thread(
    engine: Engine, storage: ObjectStorage, company_id: UUID, key: str, before: str | None, limit: int
) -> ChatThread:
    chat_key = chat_repo.parse_chat_key(key)
    cursor = parse_cursor(before) if before else None
    with Session(engine) as session:
        messages = chat_repo.chat_messages(session, company_id, chat_key, before=cursor, limit=limit)
        if not messages and (
            cursor is None or not chat_repo.chat_messages(session, company_id, chat_key, before=None, limit=1)
        ):
            raise ChatNotFoundError  # an empty `before` page of a chat that has messages is just the end of history
        ids = [m.id for m in messages]
        found = attachments_for(session, company_id, ids)
        flags = suspicious_flags(session, company_id, ids)
        refs = {str(m.meta["reply_to"]) for m in messages if m.meta.get("reply_to")}
        quoted = chat_repo.quoted_messages(session, company_id, chat_key, refs)
        name, kind = chat_repo.chat_contact(session, company_id, chat_key)
        case_id = chat_repo.latest_case_id(session, company_id, chat_key)
        by_message: dict[UUID, list[AttachmentOut]] = defaultdict(list)
        for a in found:
            by_message[a.message_id].append(_attachment(a, storage))
        out = [_to_message(m, by_message[m.id], flags.get(m.id, (False, None)), _quote_of(m, quoted)) for m in messages]
    log.info("chats.thread_read", messages=len(out))
    return ChatThread(chat_key=chat_key, name=name, person_kind=kind, case_id=case_id, messages=out)


def _mark_read(engine: Engine, company_id: UUID, key: str) -> None:
    chat_key = chat_repo.parse_chat_key(key)
    with Session(engine) as session, session.begin():
        if not chat_repo.chat_messages(session, company_id, chat_key, before=None, limit=1):
            raise ChatNotFoundError
        chat_repo.mark_read(session, company_id, chat_key, datetime.now(UTC))


@router.get("")
async def list_chats(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    filter: chat_repo.ChatFilter = "all",
    q: Annotated[str | None, Query(max_length=MAX_QUERY_LEN)] = None,
) -> list[ChatItem]:
    try:
        return await run_in_threadpool(_read_list, engine, principal.company_id, before, limit, filter, q)
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None


@router.get("/{chat_key}/messages")
async def get_chat_messages(
    chat_key: str,
    engine: Annotated[Engine, Depends(get_engine)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
    principal: Annotated[Principal, Depends(require_session)],
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_THREAD_MESSAGES)] = 100,
) -> ChatThread:
    try:
        return await run_in_threadpool(_read_thread, engine, storage, principal.company_id, chat_key, before, limit)
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None
    except (chat_repo.BadChatKeyError, ChatNotFoundError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


@router.post("/{chat_key}/read", status_code=204)
async def read_chat(
    chat_key: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> Response:
    try:
        await run_in_threadpool(_mark_read, engine, principal.company_id, chat_key)
    except (chat_repo.BadChatKeyError, ChatNotFoundError):
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    return Response(status_code=204)

"""Inbox (one row per thread) and thread detail. Read-only; message text is returned as data, never logged."""

from collections import defaultdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import AttachmentOut, InboxItem, ThreadMessage
from app.db.models.ingestion import AttachmentRow, MessageRow
from app.pipeline.read_repo import (
    BadCursorError,
    BadThreadKeyError,
    attachments_for,
    inbox_page,
    parse_cursor,
    thread_messages,
)
from app.storage.ports import MAX_PRESIGN_TTL_S, ObjectStorage

router = APIRouter(tags=["inbox"])
NOT_FOUND = "thread not found"  # one body for malformed, unknown and foreign keys: nothing to tell them apart


def _read_inbox(engine: Engine, company_id: UUID, before: str | None, limit: int) -> list[InboxItem]:
    cursor = parse_cursor(before) if before else None
    with Session(engine) as session:
        rows = inbox_page(session, company_id, before=cursor, limit=limit)
    return [
        InboxItem(
            **{k: getattr(r, k) for k in InboxItem.model_fields if k not in ("cursor", "thread_key")},
            thread_key=r.thread_key,
            cursor=f"{r.last_at.isoformat()}|{r.last_message_id}",
        )
        for r in rows
    ]


def _attachment(a: AttachmentRow, storage: ObjectStorage) -> AttachmentOut:
    return AttachmentOut(
        id=a.id,
        filename=a.filename,
        mime_type=a.mime_type,
        size_bytes=a.size_bytes,
        url=storage.presigned_url(a.s3_key, MAX_PRESIGN_TTL_S),
    )


def _message(m: MessageRow, atts: list[AttachmentOut]) -> ThreadMessage:
    return ThreadMessage(
        id=m.id,
        direction=m.direction,
        sent_at=m.sent_at,
        sender=m.sender_identity,
        text=m.text,
        delivery_status=m.delivery_status,
        pipeline_status=m.pipeline_status,
        suspicious=bool(m.meta.get("suspicious")),
        attachments=atts,
    )


def _read_thread(engine: Engine, storage: ObjectStorage, company_id: UUID, key: str) -> list[ThreadMessage]:
    with Session(engine) as session:
        messages = thread_messages(session, company_id, key)
        found = attachments_for(session, company_id, [m.id for m in messages]) if messages else []
    by_message: dict[UUID, list[AttachmentOut]] = defaultdict(list)
    for a in found:
        by_message[a.message_id].append(_attachment(a, storage))
    return [_message(m, by_message[m.id]) for m in messages]


@router.get("/inbox")
async def get_inbox(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    before: str | None = None,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> list[InboxItem]:
    try:
        return await run_in_threadpool(_read_inbox, request.app.state.engine, principal.company_id, before, limit)
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None


@router.get("/threads/{thread_key}")
async def get_thread(
    request: Request,
    thread_key: str,
    principal: Annotated[Principal, Depends(require_principal)],
    storage: Annotated[ObjectStorage, Depends(get_storage)],
) -> list[ThreadMessage]:
    try:
        messages = await run_in_threadpool(
            _read_thread, request.app.state.engine, storage, principal.company_id, thread_key
        )
    except BadThreadKeyError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None
    if not messages:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return messages

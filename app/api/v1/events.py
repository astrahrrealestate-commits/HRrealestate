"""Owner feed: paged JSON (`/feed`) and a Server-Sent Events stream (`/events`).

Postgres is the source of truth; the stream just polls it, so a restart or dropped connection loses nothing:
the client reconnects with `Last-Event-ID` (the cursor of the last event it saw) and resumes.
The stream also carries Super Agent `turn` events; their cursor scheme is in `app.api.v1.turn_events`.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import FeedItem
from app.api.v1.turn_events import TurnPoller
from app.pipeline.read_repo import MAX_PAGE, BadCursorError, Cursor, feed_page, parse_cursor

POLL_INTERVAL_S = 1.5
PING_INTERVAL_S = 15.0
SSE_START_LAG = timedelta(seconds=5)
MAX_LIFETIME_S = 15 * 60.0

log = structlog.get_logger(__name__)
router = APIRouter(tags=["feed"])


def _read_page(engine: Engine, company_id: UUID, after: Cursor | None, limit: int) -> list[FeedItem]:
    with Session(engine) as session:
        return [FeedItem.model_validate(r) for r in feed_page(session, company_id, after, limit)]


def _cursor_of(item: FeedItem) -> Cursor:
    return item.created_at, item.id


def frame(item: FeedItem) -> str:
    cursor = f"{item.created_at.isoformat()}|{item.id}"
    return f"id: {cursor}\nevent: feed\ndata: {item.model_dump_json()}\n\n"


def poll_frames(engine: Engine, company_id: UUID, after: Cursor) -> tuple[list[str], Cursor]:
    """One poll: the SSE frames for rows after `after` (at most one page) and the advanced cursor."""
    items = _read_page(engine, company_id, after, MAX_PAGE)
    return [frame(i) for i in items], (_cursor_of(items[-1]) if items else after)


def start_cursor(last_event_id: str | None, now: datetime | None = None) -> Cursor:
    """Resume point. A valid `Last-Event-ID` resumes exactly after it.

    Missing or unparseable (never an error): start `SSE_START_LAG` before "now", so a row that committed slightly
    late (its created_at is earlier than rows already seen) is not skipped. Duplicates are harmless: clients should
    refetch `/feed` after every (re)connect and dedupe by `FeedItem.id` (the stream carries ids).
    """
    if last_event_id:
        try:
            return parse_cursor(last_event_id)
        except BadCursorError:
            pass
    return (now or datetime.now(UTC)) - SSE_START_LAG, UUID(int=0)


async def event_stream(
    request: Request,
    engine: Engine,
    company_id: UUID,
    after: Cursor,
    poll_interval: float | None = None,
    ping_interval: float | None = None,
    max_lifetime: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    turns: TurnPoller | None = None,
) -> AsyncIterator[str]:
    """Poll loop. Ends on disconnect, on error (final `error` frame) or after `max_lifetime` so the client
    reconnects and re-authenticates."""
    poll = POLL_INTERVAL_S if poll_interval is None else poll_interval
    ping = PING_INTERVAL_S if ping_interval is None else ping_interval
    lifetime = MAX_LIFETIME_S if max_lifetime is None else max_lifetime
    started = last_sent = clock()
    while not await request.is_disconnected():
        if clock() - started >= lifetime:
            return
        try:
            frames, after = await run_in_threadpool(poll_frames, engine, company_id, after)
            if turns is not None:
                frames += await run_in_threadpool(turns.poll)
        except Exception as exc:
            log.warning("dashboard.events.stream_error", error=type(exc).__name__)
            yield 'event: error\ndata: {"detail":"stream ended"}\n\n'
            return
        for f in frames:
            yield f
        now = clock()
        if frames:
            last_sent = now
        elif now - last_sent >= ping:
            last_sent = now
            yield "event: ping\ndata: {}\n\n"
        await asyncio.sleep(poll)


@router.get("/feed")
async def get_feed(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    after: str | None = None,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> list[FeedItem]:
    try:
        cursor = parse_cursor(after) if after else None
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None
    return await run_in_threadpool(_read_page, request.app.state.engine, principal.company_id, cursor, limit)


@router.get("/events")
async def get_events(
    request: Request, principal: Annotated[Principal, Depends(require_principal)]
) -> StreamingResponse:
    after = start_cursor(request.headers.get("last-event-id"))
    engine = request.app.state.engine
    turns = TurnPoller(engine, principal.company_id, principal.owner_id)
    stream = event_stream(request, engine, principal.company_id, after, turns=turns)
    return StreamingResponse(
        stream, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

"""Owner feed: paged JSON (`/feed`) and a Server-Sent Events stream (`/events`).

Postgres is the source of truth; the stream just polls it, so a restart or dropped connection loses nothing:
the client reconnects with `Last-Event-ID` (the cursor of the last event it saw) and resumes.
The stream also carries Super Agent `turn` events; their cursor scheme is in `app.api.v1.turn_events`.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import FeedItem
from app.api.v1.stream_slots import StreamSlots
from app.api.v1.turn_events import TURN_POLL_SECONDS, TurnPoller
from app.pipeline.read_repo import MAX_PAGE, BadCursorError, Cursor, feed_page, parse_cursor

POLL_INTERVAL_S = 1.5
PING_INTERVAL_S = 15.0
SSE_START_LAG = timedelta(seconds=5)
MAX_LIFETIME_S = 15 * 60.0
MAX_STREAMS_PER_OWNER = 4  # a few tabs and a reconnect overlap; more is a runaway client
SLOTS = StreamSlots(cap=MAX_STREAMS_PER_OWNER, ttl=MAX_LIFETIME_S + 60.0)

log = structlog.get_logger(__name__)
router = APIRouter(
    tags=["feed"],
    dependencies=[
        Depends(
            require_section(
                "dashboard",
                also=("inbox", "properties", "tenants", "contacts", "maintenance", "money", "reports", "settings"),
            )
        )
    ],
)


def _read_page(
    engine: Engine, company_id: UUID, after: Cursor | None, limit: int, *, full: bool = True
) -> list[FeedItem]:
    with Session(engine) as session:
        items = [FeedItem.model_validate(r) for r in feed_page(session, company_id, after, limit)]
    # A card's payload holds the draft replies and what the sender wrote: only Inbox and Maintenance see it (ADR 0012).
    return items if full else [i.model_copy(update={"payload": {}}) for i in items]


def _cursor_of(item: FeedItem) -> Cursor:
    return item.created_at, item.id


def frame(item: FeedItem) -> str:
    cursor = f"{item.created_at.isoformat()}|{item.id}"
    return f"id: {cursor}\nevent: feed\ndata: {item.model_dump_json()}\n\n"


def poll_frames(engine: Engine, company_id: UUID, after: Cursor, *, full: bool = True) -> tuple[list[str], Cursor]:
    """One poll: the SSE frames for rows after `after` (at most one page) and the advanced cursor."""
    items = _read_page(engine, company_id, after, MAX_PAGE, full=full)
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


def tick_seconds(feed_poll: float, turn_poll: float | None, turns: bool) -> float:
    """The loop's sleep: the turn interval (default `TURN_POLL_SECONDS`) when turns are polled, else the feed's."""
    return min(feed_poll, TURN_POLL_SECONDS if turn_poll is None else turn_poll) if turns else feed_poll


def feed_due(now: float, next_feed: float, tick: float) -> bool:
    """Half a tick of slack: a sleep that wakes a hair early still polls the feed on its 1.5 s beat."""
    return now >= next_feed - tick / 2


async def _poll(
    engine: Engine, company_id: UUID, after: Cursor, turns: TurnPoller | None, *, feed: bool, full: bool = True
) -> tuple[list[str], Cursor]:
    """One tick: the feed page when it is due, then the turn changes (both in the thread pool)."""
    frames: list[str] = []
    if feed:
        frames, after = await run_in_threadpool(partial(poll_frames, full=full), engine, company_id, after)
    if turns is not None:
        frames += await run_in_threadpool(turns.poll)
    return frames, after


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
    turn_poll_interval: float | None = None,
    full: bool = True,
) -> AsyncIterator[str]:
    """Poll loop: turns every `TURN_POLL_SECONDS`, the feed every `POLL_INTERVAL_S`. Ends on disconnect, on error
    (final `error` frame) or after `max_lifetime` so the client reconnects and re-authenticates."""
    poll = POLL_INTERVAL_S if poll_interval is None else poll_interval
    ping = PING_INTERVAL_S if ping_interval is None else ping_interval
    lifetime = MAX_LIFETIME_S if max_lifetime is None else max_lifetime
    tick = tick_seconds(poll, turn_poll_interval, turns is not None)
    started = last_sent = next_feed = clock()
    while not await request.is_disconnected():
        now = clock()
        if now - started >= lifetime:
            return
        due = feed_due(now, next_feed, tick)
        try:
            frames, after = await _poll(engine, company_id, after, turns, feed=due, full=full)
        except Exception as exc:
            log.warning("dashboard.events.stream_error", error=type(exc).__name__)
            yield 'event: error\ndata: {"detail":"stream ended"}\n\n'
            return
        next_feed = now + poll if due else next_feed
        for f in frames:
            yield f
        now = clock()
        if frames:
            last_sent = now
        elif now - last_sent >= ping:
            last_sent = now
            yield "event: ping\ndata: {}\n\n"
        await asyncio.sleep(tick)


def _sees_cards(principal: Principal) -> bool:
    return principal.access.can("inbox") or principal.access.can("maintenance")


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
    full = _sees_cards(principal)
    return await run_in_threadpool(
        partial(_read_page, full=full), request.app.state.engine, principal.company_id, cursor, limit
    )


async def _holding(stream: AsyncIterator[str], owner_id: UUID, token: int) -> AsyncIterator[str]:
    """Yield the stream, then give the owner's place back however it ended."""
    try:
        async for chunk in stream:
            yield chunk
    finally:
        SLOTS.release(owner_id, token)


@router.get("/events")
async def get_events(
    request: Request, principal: Annotated[Principal, Depends(require_principal)]
) -> StreamingResponse:
    token = SLOTS.acquire(principal.owner_id)
    if token is None:
        raise HTTPException(status_code=429, detail="too many open event streams", headers={"Retry-After": "30"})
    after = start_cursor(request.headers.get("last-event-id"))
    engine = request.app.state.engine
    turns = TurnPoller(engine, principal.company_id, principal.owner_id)
    stream = event_stream(request, engine, principal.company_id, after, turns=turns, full=_sees_cards(principal))
    return StreamingResponse(
        _holding(stream, principal.owner_id, token),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

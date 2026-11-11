import asyncio
import itertools
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1 import events
from app.api.v1.auth import COOKIE, Principal, issue_session
from app.api.v1.schemas import FeedItem
from app.core.settings import Settings
from app.db.enums import FeedKind
from app.main import create_app
from app.pipeline.read_repo import BadCursorError, parse_cursor

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=uuid4(), owner_id=uuid4(), email="h@example.test")
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _item(n: int) -> FeedItem:
    return FeedItem(
        id=UUID(int=n), kind=FeedKind.alert, ref_id=None, payload={}, created_at=T0, seen_at=None, resolved_at=None
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def test_cursor_roundtrip() -> None:
    assert parse_cursor(f"{T0.isoformat()}|{UUID(int=5)}") == (T0, UUID(int=5))


@pytest.mark.parametrize("raw", ["", "garbage", "x|y", f"{T0.isoformat()}|nope", f"2026-01-01T00:00:00|{UUID(int=1)}"])
def test_bad_cursor_rejected(raw: str) -> None:
    with pytest.raises(BadCursorError):
        parse_cursor(raw)


def test_feed_bad_cursor_422(client: TestClient) -> None:
    assert client.get("/api/v1/feed", params={"after": "junk"}).status_code == 422


def test_feed_requires_auth() -> None:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app) as c:
        assert c.get("/api/v1/feed").status_code == 401
        assert c.get("/api/v1/events").status_code == 401


def test_feed_scopes_to_principal_company(client: TestClient) -> None:
    with patch("app.api.v1.events._read_page", return_value=[_item(1)]) as page:
        r = client.get("/api/v1/feed", params={"limit": 500})
    assert r.status_code == 200
    assert page.call_args.args[1] == PRINCIPAL.company_id
    assert [x["id"] for x in r.json()] == [str(UUID(int=1))]


def test_poll_frames_advances_cursor() -> None:
    with patch("app.api.v1.events._read_page", return_value=[_item(1), _item(2)]):
        frames, cursor = events.poll_frames(MagicMock(), uuid4(), (T0, UUID(int=0)))
    assert cursor == (T0, UUID(int=2))
    assert frames[0].startswith(f"id: {T0.isoformat()}|{UUID(int=1)}\nevent: feed\ndata: {{")
    assert frames[0].endswith("\n\n")


def test_poll_frames_empty_keeps_cursor() -> None:
    start = (T0, UUID(int=9))
    with patch("app.api.v1.events._read_page", return_value=[]):
        assert events.poll_frames(MagicMock(), uuid4(), start) == ([], start)


def test_start_cursor_without_valid_header_lags_now() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    expected = (now - events.SSE_START_LAG, UUID(int=0))
    assert events.start_cursor("garbage", now) == expected
    assert events.start_cursor(None, now) == expected
    assert events.start_cursor(f"{T0.isoformat()}|{UUID(int=3)}", now) == (T0, UUID(int=3))


def test_cursor_plus_decoded_as_space_is_normalized() -> None:
    stamp = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))
    raw = f"{stamp.isoformat()}|{UUID(int=4)}".replace("+", " ")
    assert parse_cursor(raw) == (stamp, UUID(int=4))


def test_feed_accepts_space_for_plus(client: TestClient) -> None:
    cursor = f"2026-01-01T00:00:00 02:00|{UUID(int=1)}"
    with patch("app.api.v1.events._read_page", return_value=[]) as page:
        assert client.get("/api/v1/feed", params={"after": cursor}).status_code == 200
    assert page.call_args.args[2] is not None


def _stream(request: MagicMock, **kw: Any) -> list[str]:
    async def collect() -> list[str]:
        gen = events.event_stream(request, MagicMock(), uuid4(), (T0, UUID(int=0)), poll_interval=0, **kw)
        return [f async for f in gen]

    return asyncio.run(collect())


def _connected(request: MagicMock) -> None:
    async def never() -> bool:
        return False

    request.is_disconnected = never


def test_event_stream_error_emits_error_frame_and_stops() -> None:
    request = MagicMock()
    _connected(request)
    with patch("app.api.v1.events._read_page", side_effect=RuntimeError("secret detail")):
        out = _stream(request)
    assert out == ['event: error\ndata: {"detail":"stream ended"}\n\n']


def test_event_stream_ends_after_max_lifetime() -> None:
    request = MagicMock()
    _connected(request)
    ticks = itertools.count(0, 10)
    with patch("app.api.v1.events._read_page", return_value=[]):
        out = _stream(request, ping_interval=1000, max_lifetime=25, clock=lambda: float(next(ticks)))
    assert out == []


def test_event_stream_emits_feed_then_ping_then_stops() -> None:
    request = MagicMock()
    disconnected = iter([False, False, True])

    async def is_disconnected() -> bool:
        return next(disconnected)

    request.is_disconnected = is_disconnected
    pages = iter([[_item(1)], []])

    def fake_read(*_: object, **__: object) -> list[FeedItem]:
        return next(pages)

    async def collect() -> list[str]:
        gen = events.event_stream(request, MagicMock(), uuid4(), (T0, UUID(int=0)), poll_interval=0, ping_interval=0)
        return [f async for f in gen]

    with patch("app.api.v1.events._read_page", side_effect=fake_read):
        out = asyncio.run(collect())
    assert out[0].startswith("id: ")
    assert "event: feed" in out[0]
    assert out[1] == "event: ping\ndata: {}\n\n"


def test_poll_pages_identical_created_at_without_skips() -> None:
    """Rows sharing created_at are ordered by id; the cursor carries both, so limit=1 paging loses nothing."""
    rows = [_item(1), _item(2), _item(3)]

    def fake_read(_e: object, _c: object, after: tuple[datetime, UUID], _limit: int, **_: object) -> list[FeedItem]:
        return [r for r in rows if (r.created_at, r.id) > after][:1]

    cursor = (T0, UUID(int=0))
    seen: list[UUID] = []
    with patch("app.api.v1.events._read_page", side_effect=fake_read):
        for _ in range(4):
            frames, cursor = events.poll_frames(MagicMock(), uuid4(), cursor)
            seen += [UUID(f.split("|")[1].split("\n")[0]) for f in frames]
    assert seen == [UUID(int=1), UUID(int=2), UUID(int=3)]


def test_events_refuse_an_owner_who_holds_too_many_streams(client: TestClient) -> None:
    with patch.object(events, "SLOTS", events.StreamSlots(cap=0, ttl=60.0)):
        response = client.get("/api/v1/events")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"

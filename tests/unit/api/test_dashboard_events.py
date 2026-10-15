import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
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


def test_start_cursor_bad_header_means_now() -> None:
    before = datetime.now(UTC)
    assert events.start_cursor("garbage")[0] >= before
    assert events.start_cursor(None)[0] >= before
    assert events.start_cursor(f"{T0.isoformat()}|{UUID(int=3)}") == (T0, UUID(int=3))


def test_event_stream_emits_feed_then_ping_then_stops() -> None:
    request = MagicMock()
    disconnected = iter([False, False, True])

    async def is_disconnected() -> bool:
        return next(disconnected)

    request.is_disconnected = is_disconnected
    pages = iter([[_item(1)], []])

    def fake_read(*_: object) -> list[FeedItem]:
        return next(pages)

    async def collect() -> list[str]:
        gen = events.event_stream(request, MagicMock(), uuid4(), (T0, UUID(int=0)), poll_interval=0, ping_interval=0)
        return [f async for f in gen]

    with patch("app.api.v1.events._read_page", side_effect=fake_read):
        out = asyncio.run(collect())
    assert out[0].startswith("id: ")
    assert "event: feed" in out[0]
    assert out[1] == "event: ping\ndata: {}\n\n"

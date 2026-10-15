import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from app.api.v1 import events, turn_events
from app.api.v1.schemas import FeedItem, TurnEvent
from app.db.enums import FeedKind, TurnStatus

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
P = "app.api.v1.turn_events.read_turn_events"


def _turn(n: int, status: TurnStatus = TurnStatus.done, at: datetime = T0) -> TurnEvent:
    return TurnEvent(id=UUID(int=n), conversation_id=UUID(int=99), status=status, answer=f"a{n}", updated_at=at)


def test_turn_frame_has_no_id_so_last_event_id_stays_the_feed_cursor() -> None:
    frame = turn_events.turn_frame(_turn(1))
    assert frame.startswith("event: turn\ndata: {")
    assert "\nid:" not in frame
    assert not frame.startswith("id:")
    assert frame.endswith("\n\n")
    data = json.loads(frame.split("data: ", 1)[1])
    assert data == {
        "id": str(UUID(int=1)),
        "conversation_id": str(UUID(int=99)),
        "status": "done",
        "answer": "a1",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_poller_starts_five_minutes_back_and_is_owner_scoped() -> None:
    company, owner = uuid4(), uuid4()
    poller = turn_events.TurnPoller(MagicMock(), company, owner, now=NOW)
    with patch(P, return_value=[]) as read:
        assert poller.poll() == []
    assert read.call_args.args[1:] == (company, owner, (NOW - timedelta(minutes=5), UUID(int=0)))


def test_poller_advances_its_cursor_and_emits_each_change_once() -> None:
    later = T0 + timedelta(seconds=1)
    rows = [_turn(1, TurnStatus.running, T0), _turn(1, TurnStatus.done, later)]

    def fake_read(_e: object, _c: object, _o: object, after: tuple[datetime, UUID]) -> list[TurnEvent]:
        return [r for r in rows if (r.updated_at, r.id) > after][:1]

    poller = turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=T0)
    seen: list[str] = []
    with patch(P, side_effect=fake_read):
        for _ in range(3):
            seen += [json.loads(f.split("data: ", 1)[1])["status"] for f in poller.poll()]
    assert seen == ["running", "done"]
    assert poller.after == (later, UUID(int=1))


def _connected_twice() -> MagicMock:
    request = MagicMock()
    states = iter([False, True])

    async def is_disconnected() -> bool:
        return next(states)

    request.is_disconnected = is_disconnected
    return request


def _collect(request: MagicMock, **kw: Any) -> list[str]:
    async def run() -> list[str]:
        gen = events.event_stream(request, MagicMock(), uuid4(), (T0, UUID(int=0)), poll_interval=0, **kw)
        return [f async for f in gen]

    return asyncio.run(run())


def test_stream_carries_feed_then_turn_frames() -> None:
    item = FeedItem(
        id=UUID(int=1), kind=FeedKind.alert, ref_id=None, payload={}, created_at=T0, seen_at=None, resolved_at=None
    )
    poller = turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=NOW)
    with patch("app.api.v1.events._read_page", return_value=[item]), patch(P, return_value=[_turn(2)]):
        out = _collect(_connected_twice(), turns=poller)
    assert out[0].startswith("id: ")
    assert "event: feed" in out[0]
    assert out[1].startswith("event: turn\n")


def test_turn_read_error_ends_the_stream_with_error_frame() -> None:
    poller = turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=NOW)
    with patch("app.api.v1.events._read_page", return_value=[]), patch(P, side_effect=RuntimeError("secret")):
        out = _collect(_connected_twice(), turns=poller)
    assert out == ['event: error\ndata: {"detail":"stream ended"}\n\n']

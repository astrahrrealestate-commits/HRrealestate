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
    since = NOW - timedelta(minutes=5) - turn_events.OVERLAP
    assert read.call_args.args[1:] == (company, owner, (since, UUID(int=0)))


class FakeTurns:
    """The agent_turns table as the poller sees it: one current row per turn id."""

    def __init__(self) -> None:
        self.rows: dict[UUID, TurnEvent] = {}
        self.queries: list[tuple[datetime, UUID]] = []

    def set(self, event: TurnEvent) -> None:
        self.rows[event.id] = event

    def read(self, _e: object, _c: object, _o: object, after: tuple[datetime, UUID]) -> list[TurnEvent]:
        self.queries.append(after)
        return sorted(
            (r for r in self.rows.values() if (r.updated_at, r.id) > after), key=lambda r: (r.updated_at, r.id)
        )


def _statuses(frames: list[str]) -> list[str]:
    return [json.loads(f.split("data: ", 1)[1])["status"] for f in frames]


def test_each_change_is_sent_once_despite_the_overlap_reread() -> None:
    table, poller = FakeTurns(), turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=T0)
    table.set(_turn(1, TurnStatus.running, T0))
    with patch(P, side_effect=table.read):
        first = poller.poll()
        again = poller.poll()  # re-reads the overlap window: nothing new
        table.set(_turn(1, TurnStatus.done, T0 + timedelta(seconds=1)))
        done = poller.poll()
        last = poller.poll()
    assert (_statuses(first), again, _statuses(done), last) == (["running"], [], ["done"], [])
    assert poller.after == (T0 + timedelta(seconds=1), UUID(int=1))
    assert table.queries[-1][0] == T0 + timedelta(seconds=1) - turn_events.OVERLAP


def test_late_commit_behind_the_cursor_is_still_sent() -> None:
    table, poller = FakeTurns(), turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=T0)
    table.set(_turn(2, TurnStatus.running, T0 + timedelta(seconds=5)))
    with patch(P, side_effect=table.read):
        assert _statuses(poller.poll()) == ["running"]
        # stamped 1 s before the cursor, committed only now (slow transaction)
        table.set(_turn(3, TurnStatus.done, T0 + timedelta(seconds=4)))
        assert _statuses(poller.poll()) == ["done"]
        assert poller.poll() == []
    assert poller.after == (T0 + timedelta(seconds=5), UUID(int=2))


def test_sent_set_is_pruned_behind_the_window() -> None:
    table, poller = FakeTurns(), turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=T0)
    with patch(P, side_effect=table.read):
        for n in range(1, 6):
            table.set(_turn(n, TurnStatus.done, T0 + timedelta(seconds=10 * n)))
            poller.poll()
    assert poller.sent == {(UUID(int=5), T0 + timedelta(seconds=50))}


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


def test_turn_poll_is_half_a_second_and_the_feed_keeps_its_rate() -> None:
    assert turn_events.TURN_POLL_SECONDS == 0.5
    assert events.POLL_INTERVAL_S == 1.5
    assert timedelta(seconds=2) == turn_events.OVERLAP
    assert events.tick_seconds(1.5, 0.5, turns=True) == 0.5
    assert events.tick_seconds(1.5, 0.5, turns=False) == 1.5  # no turn poller: the feed's own beat


def test_feed_due_tolerates_a_sleep_that_wakes_slightly_early() -> None:
    assert events.feed_due(1.4995, 1.5, 0.5)
    assert not events.feed_due(1.0, 1.5, 0.5)


class FakeTime:
    """Monotonic time that only moves when the stream sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _connected_for(polls: int) -> MagicMock:
    request = MagicMock()
    states = iter([False] * polls + [True])

    async def is_disconnected() -> bool:
        return next(states)

    request.is_disconnected = is_disconnected
    return request


def _timed(polls: int, **kw: Any) -> tuple[FakeTime, list[float], list[float]]:
    fake, feed_at, turn_at = FakeTime(), [], []
    poller = turn_events.TurnPoller(MagicMock(), uuid4(), uuid4(), now=NOW)

    def read_page(*_: object) -> list[FeedItem]:
        feed_at.append(fake.now)
        return []

    def read_turns(*_: object) -> list[TurnEvent]:
        turn_at.append(fake.now)
        return []

    async def run() -> list[str]:
        gen = events.event_stream(
            _connected_for(polls), MagicMock(), uuid4(), (T0, UUID(int=0)), clock=fake.clock, turns=poller, **kw
        )
        return [f async for f in gen]

    with (
        patch("app.api.v1.events._read_page", side_effect=read_page),
        patch(P, side_effect=read_turns),
        patch("app.api.v1.events.asyncio.sleep", fake.sleep),
    ):
        asyncio.run(run())
    return fake, feed_at, turn_at


def test_turns_are_polled_every_half_second_and_the_feed_every_one_and_a_half() -> None:
    fake, feed_at, turn_at = _timed(7)
    assert fake.sleeps == [0.5] * 7
    assert turn_at == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]  # about 2 indexed turn reads per second
    assert feed_at == [0.0, 1.5, 3.0]


def test_turn_poll_interval_is_injectable() -> None:
    fake, feed_at, turn_at = _timed(4, turn_poll_interval=1.5)
    assert fake.sleeps == [1.5] * 4
    assert turn_at == feed_at == [0.0, 1.5, 3.0, 4.5]


def test_without_turns_the_stream_keeps_the_feed_beat() -> None:
    fake = FakeTime()

    async def run() -> list[str]:
        gen = events.event_stream(_connected_for(3), MagicMock(), uuid4(), (T0, UUID(int=0)), clock=fake.clock)
        return [f async for f in gen]

    with patch("app.api.v1.events._read_page", return_value=[]), patch("app.api.v1.events.asyncio.sleep", fake.sleep):
        asyncio.run(run())
    assert fake.sleeps == [1.5] * 3

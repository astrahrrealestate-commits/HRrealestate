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

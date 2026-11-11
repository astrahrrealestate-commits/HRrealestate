"""One owner can hold only a few live event streams, so a tab loop cannot exhaust the server's polling threads."""

from uuid import UUID

from app.api.v1.stream_slots import StreamSlots

OWNER = UUID(int=1)
OTHER = UUID(int=2)


def test_an_owner_gets_the_cap_and_no_more() -> None:
    slots = StreamSlots(cap=2, ttl=100.0, clock=lambda: 0.0)
    first, second = slots.acquire(OWNER), slots.acquire(OWNER)
    assert first is not None
    assert second is not None
    assert slots.acquire(OWNER) is None


def test_the_cap_is_per_owner() -> None:
    slots = StreamSlots(cap=1, ttl=100.0, clock=lambda: 0.0)
    assert slots.acquire(OWNER) is not None
    assert slots.acquire(OTHER) is not None


def test_releasing_frees_the_place() -> None:
    slots = StreamSlots(cap=1, ttl=100.0, clock=lambda: 0.0)
    token = slots.acquire(OWNER)
    assert token is not None
    slots.release(OWNER, token)
    assert slots.acquire(OWNER) is not None


def test_a_stream_that_never_started_stops_counting_after_the_ttl() -> None:
    now = [0.0]
    slots = StreamSlots(cap=1, ttl=100.0, clock=lambda: now[0])
    assert slots.acquire(OWNER) is not None
    assert slots.acquire(OWNER) is None
    now[0] = 101.0
    assert slots.acquire(OWNER) is not None


def test_releasing_twice_or_an_unknown_token_is_harmless() -> None:
    slots = StreamSlots(cap=1, ttl=100.0, clock=lambda: 0.0)
    token = slots.acquire(OWNER)
    assert token is not None
    slots.release(OWNER, token)
    slots.release(OWNER, token)
    slots.release(OTHER, 99)

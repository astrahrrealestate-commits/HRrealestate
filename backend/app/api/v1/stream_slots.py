"""A cap on the live event streams one owner may hold (the stream polls Postgres in the thread pool).

In-process like the other v1 limiters (per worker, ADR 0006). A place expires after `ttl` so a response that never
started its generator cannot hold it forever.
"""

import itertools
import time
from collections.abc import Callable
from uuid import UUID


class StreamSlots:
    def __init__(self, cap: int, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._cap = cap
        self._ttl = ttl
        self._clock = clock
        self._open: dict[UUID, dict[int, float]] = {}
        self._tokens = itertools.count(1)

    def acquire(self, owner_id: UUID) -> int | None:
        """A token for a new stream, or None when the owner already holds the cap."""
        now = self._clock()
        held = {t: at for t, at in self._open.get(owner_id, {}).items() if now - at < self._ttl}
        if len(held) >= self._cap:
            self._open[owner_id] = held
            return None
        token = next(self._tokens)
        held[token] = now
        self._open[owner_id] = held
        return token

    def release(self, owner_id: UUID, token: int) -> None:
        held = self._open.get(owner_id)
        if held is not None:
            held.pop(token, None)
            if not held:
                del self._open[owner_id]

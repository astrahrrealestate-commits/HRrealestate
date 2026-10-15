"""In-process token buckets for the dashboard API (single worker, Phase 1).

State lives in this process, so limits are per worker. Running several API instances needs Postgres-backed counters
(no Redis, ADR 0006). Buckets are keyed by (route group, principal id or client ip); idle buckets are evicted and the
table is capped, so memory stays bounded.
"""

import math
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException, Request

AGENT_PER_MIN = 30
AUTH_PER_MIN = 10
DECISION_PER_MIN = 120
MAX_BUCKETS = 10_000
SWEEP_EVERY = 256
DETAIL = "rate_limited"

Key = tuple[str, str]


class RateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_buckets: int = MAX_BUCKETS) -> None:
        self._clock = clock
        self._max = max_buckets
        self._buckets: dict[Key, tuple[float, float]] = {}  # key -> (tokens, last refill time)
        self._calls = 0
        self._lock = threading.Lock()

    def check(self, group: str, subject: str, per_minute: int) -> int | None:
        """Take one token. Returns None when allowed, else whole seconds to wait."""
        now = self._clock()
        rate = per_minute / 60.0
        with self._lock:
            self._calls += 1
            if self._calls % SWEEP_EVERY == 0 or len(self._buckets) >= self._max:
                self._sweep(now, per_minute)
            tokens, last = self._buckets.get((group, subject), (float(per_minute), now))
            tokens = min(float(per_minute), tokens + max(0.0, now - last) * rate)
            if tokens >= 1.0:
                self._buckets[(group, subject)] = (tokens - 1.0, now)
                return None
            self._buckets[(group, subject)] = (tokens, now)
            return max(1, math.ceil((1.0 - tokens) / rate))

    def _sweep(self, now: float, per_minute: int) -> None:
        idle = [k for k, (_, last) in self._buckets.items() if now - last >= 60.0]
        for key in idle:  # a bucket idle for a full window has refilled: forgetting it changes nothing
            del self._buckets[key]
        if len(self._buckets) >= self._max:  # still full of busy keys: drop the least recently used half
            by_age = sorted(self._buckets, key=lambda k: self._buckets[k][1])
            for key in by_age[: len(by_age) // 2]:
                del self._buckets[key]

    def size(self) -> int:
        return len(self._buckets)


def limiter_for(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter  # created once in create_app
    return limiter


def client_ip(request: Request) -> str:
    if request.app.state.settings.dashboard_trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()  # the entry our own proxy appended
    return request.client.host if request.client else "unknown"


def _reject(retry_after: int) -> HTTPException:
    return HTTPException(status_code=429, detail=DETAIL, headers={"Retry-After": str(retry_after)})


def limit_principal(group: str, per_minute: int) -> Callable[..., None]:
    def dependency(request: Request) -> None:
        from app.api.v1.auth import cookie_principal  # auth imports this module for the login limit

        who = cookie_principal(request)  # 401 before any token is taken (the route re-checks the owner row)
        wait = limiter_for(request).check(group, str(who.owner_id), per_minute)
        if wait is not None:
            raise _reject(wait)

    return dependency


def limit_ip(group: str, per_minute: int) -> Callable[..., None]:
    def dependency(request: Request) -> None:
        wait = limiter_for(request).check(group, client_ip(request), per_minute)
        if wait is not None:
            raise _reject(wait)

    return dependency


agent_limit = limit_principal("agent", AGENT_PER_MIN)
auth_limit = limit_ip("auth", AUTH_PER_MIN)
decision_limit = limit_principal("decision", DECISION_PER_MIN)

"""Rate limits for the dashboard routers (agent, inbox, maintenance, calendar), keyed by the signed-in owner.

The v1 limiters read the cookie themselves; these depend on `require_session`, so they take the same principal the
route does (one session check per request) and a test that signs in as an owner is limited as that owner too.
Same in-process buckets as `ratelimit` (per worker, ADR 0006).
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.api.v1.auth import Principal, require_session
from app.api.v1.ratelimit import AGENT_PER_MIN, DECISION_PER_MIN, _reject, limiter_for

TRANSLATE_PER_MIN = 30  # a first open of a Dutch message or draft; cached texts never reach the model
SYNC_PER_MIN = 6  # each call pulls Gmail and starts the AI pipeline: it costs money


def limit_session(group: str, per_minute: int) -> Callable[..., None]:
    def dependency(request: Request, principal: Annotated[Principal, Depends(require_session)]) -> None:
        wait = limiter_for(request).check(group, str(principal.owner_id), per_minute)
        if wait is not None:
            raise _reject(wait)

    return dependency


ask_limit = limit_session("agent", AGENT_PER_MIN)
decide_limit = limit_session("decision", DECISION_PER_MIN)
sync_limit = limit_session("sync", SYNC_PER_MIN)
translate_limit = limit_session("translate", TRANSLATE_PER_MIN)

"""Rate limits on the dashboard cost and approval routes: per signed-in owner, with a Retry-After."""

from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.v1.auth import Principal, require_session
from app.api.v1.ratelimit import DETAIL, RateLimiter
from app.api.v1.session_limits import limit_session
from app.core.settings import Settings

ALICE = Principal(company_id=UUID(int=1), owner_id=UUID(int=10), email="a@x.test")
BOB = Principal(company_id=UUID(int=1), owner_id=UUID(int=11), email="b@x.test")


@pytest.fixture
def app() -> FastAPI:
    api = FastAPI()
    api.state.rate_limiter = RateLimiter()
    api.state.settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[call-arg]

    @api.post("/work", dependencies=[Depends(limit_session("test", 2))])
    def work() -> dict[str, bool]:
        return {"ok": True}

    return api


def _as(app: FastAPI, principal: Principal) -> TestClient:
    app.dependency_overrides[require_session] = lambda: principal
    return TestClient(app)


def test_the_third_call_in_a_minute_is_refused_with_a_retry_after(app: FastAPI) -> None:
    client = _as(app, ALICE)
    assert [client.post("/work").status_code for _ in range(3)] == [200, 200, 429]
    refused = client.post("/work")
    assert refused.json() == {"detail": DETAIL}
    assert int(refused.headers["retry-after"]) >= 1


def test_each_owner_has_their_own_bucket(app: FastAPI) -> None:
    alice = _as(app, ALICE)
    assert [alice.post("/work").status_code for _ in range(3)] == [200, 200, 429]
    bob = _as(app, BOB)
    assert bob.post("/work").status_code == 200


def test_the_real_routes_carry_the_limits() -> None:
    from app.api.agent.routes import router as agent
    from app.api.calendar.routes import router as calendar
    from app.api.inbox.routes import router as inbox
    from app.api.inbox.translate import router as translate
    from app.api.maintenance.routes import router as maintenance

    def limited(router: object, path: str) -> bool:
        route = next(r for r in router.routes if getattr(r, "path", "") == path)  # type: ignore[attr-defined]
        return any(d.dependency.__qualname__.startswith("limit_session") for d in route.dependencies)

    assert limited(agent, "/api/agent/ask")
    assert limited(inbox, "/api/inbox/sync")
    assert limited(translate, "/translate")  # included into the inbox router (prefix /api/inbox)
    assert limited(inbox, "/api/inbox/approvals/{approval_id}/decide")
    assert limited(maintenance, "/api/maintenance/tickets/{ticket_id}/approve")
    assert limited(calendar, "/api/calendar/events/{event_id}/approve")

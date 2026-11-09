"""Test helper: act as the signed-in owner on the dashboard routers without a real cookie.

`require_session` guards every dashboard router; overriding it gives a handler a fixed `Principal`, exactly what the
cookie would have produced. Tests that exercise the guard itself (test_route_auth_guard) do not use this.
"""

from uuid import UUID

from fastapi import FastAPI

from app.api.v1.auth import Principal, require_session

OWNER = Principal(company_id=UUID(int=1), owner_id=UUID(int=2), email="harjot@example.test")


def as_owner(app: FastAPI, principal: Principal = OWNER) -> FastAPI:
    app.dependency_overrides[require_session] = lambda: principal
    return app

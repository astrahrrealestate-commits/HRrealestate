"""Test helper: act as the signed-in owner on the dashboard routers without a real cookie.

`require_session` guards every dashboard router; overriding it gives a handler a fixed `Principal`, exactly what the
cookie would have produced. Tests that exercise the guard itself (test_route_auth_guard) do not use this.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI

from app.api.v1.auth import Principal, require_session
from app.db.models import AgentConversation

OWNER = Principal(company_id=UUID(int=1), owner_id=UUID(int=2), email="harjot@example.test")


def as_owner(app: FastAPI, principal: Principal = OWNER) -> FastAPI:
    app.dependency_overrides[require_session] = lambda: principal
    return app


def with_conversation(getter: Callable[[Any, Any], Any]) -> Callable[[Any, Any], Any]:
    """Wrap a fake `session.get`: an `AgentConversation` always exists for the signed-in owner, as it does in a real
    database (the ask route creates it before it answers). Everything else is delegated to `getter`."""

    def get(model: Any, ident: Any) -> Any:
        found = getter(model, ident)
        if found is None and model is AgentConversation:
            return AgentConversation(
                id=ident or uuid4(), company_id=OWNER.company_id, owner_id=OWNER.owner_id, title="New Chat"
            )
        return found

    return get

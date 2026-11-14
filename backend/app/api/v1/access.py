"""Route guards for profile access: a section a profile was granted, or the admin role (ADR 0012)."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.api.v1.auth import SAFE_METHODS, Principal, require_principal, require_session

NO_ACCESS = "your profile has no access to this section"
NO_AGENT = "the Super Agent reads the whole portfolio; your profile does not open every section"


def require_section(
    section: str, *, also: tuple[str, ...] = (), also_read: tuple[str, ...] = ()
) -> Callable[..., Awaitable[Principal]]:
    """Dependency: a valid session whose profile may open `section`, or any section in `also` (pages that share the
    workflow). Sections in `also_read` may also read (GET) it: the Reports and Dashboard pages are built from the
    same data."""

    async def guard(request: Request, principal: Annotated[Principal, Depends(require_session)]) -> Principal:
        readable = (section, *also, *(also_read if request.method in SAFE_METHODS else ()))
        if not any(principal.access.can(s) for s in readable):
            raise HTTPException(status_code=403, detail=NO_ACCESS)
        return principal

    return guard


async def require_admin(principal: Annotated[Principal, Depends(require_session)]) -> Principal:
    """Dependency: a valid session whose profile manages the team (role owner or superadmin)."""
    if not principal.access.is_admin:
        raise HTTPException(status_code=403, detail="only a superadmin can manage profiles")
    return principal


def _agent_allowed(principal: Principal) -> Principal:
    if not principal.access.can_use_agent:
        raise HTTPException(status_code=403, detail=NO_AGENT)
    return principal


async def require_agent(principal: Annotated[Principal, Depends(require_session)]) -> Principal:
    """Dependency of the dashboard Super Agent routes (cookie session): its answers span the whole portfolio, so it is
    not scoped to one section."""
    return _agent_allowed(principal)


async def require_agent_v1(principal: Annotated[Principal, Depends(require_principal)]) -> Principal:
    """The same rule for the v1 agent routes, which resolve the principal themselves."""
    return _agent_allowed(principal)

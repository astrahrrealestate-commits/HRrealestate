"""Dashboard session auth: Google ID token -> signed httpOnly cookie -> `Principal` (company comes from here only)."""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from itsdangerous import BadData, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.ratelimit import auth_limit
from app.api.v1.sections import Access
from app.core.errors import EstateOSError
from app.core.settings import Settings
from app.db.models.tenancy import AllowedUser, OwnerAccount

log = structlog.get_logger(__name__)
COOKIE = "eo_session"
CSRF_HEADER = "X-EstateOS-Client"
CSRF_VALUE = "dashboard"
MAX_CLOCK_SKEW_S = 60
FAKE_DEFAULT_TOKENS = {"test-owner-token": "owner@example.test"}


class AuthError(EstateOSError):
    """Missing, invalid or expired credentials."""


class IdentityProviderUnavailableError(AuthError):
    """The identity provider could not be reached (maps to 503, not 401)."""


@dataclass(frozen=True)
class Principal:
    company_id: UUID
    owner_id: UUID
    email: str
    # Filled from the whitelist row on every request (`require_principal`), never from the cookie.
    access: Access = field(default_factory=Access)


class IdTokenVerifier(Protocol):
    def verify(self, token: str) -> str:
        """Return the verified email or raise AuthError."""
        ...


class FakeIdTokenVerifier:
    def __init__(self, emails: dict[str, str]) -> None:
        self._emails = emails

    def verify(self, token: str) -> str:
        try:
            return self._emails[token]
        except KeyError:
            raise AuthError("invalid id token") from None


class GoogleIdTokenVerifier:
    def __init__(self, client_id: str) -> None:
        self._client_id = client_id

    def verify(self, token: str) -> str:
        from google.auth.exceptions import GoogleAuthError, TransportError
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        try:
            claims = id_token.verify_oauth2_token(token, google_requests.Request(), self._client_id)
        except TransportError:
            raise IdentityProviderUnavailableError("identity provider unavailable") from None
        except (ValueError, GoogleAuthError):
            raise AuthError("invalid id token") from None
        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str):
            raise AuthError("email not verified")
        return email


def dashboard_verifier(settings: Settings) -> IdTokenVerifier:
    if settings.dashboard_auth_provider == "fake":
        return FakeIdTokenVerifier(dict(FAKE_DEFAULT_TOKENS))
    if not settings.google_oauth_client_id:
        raise AuthError("GOOGLE_OAUTH_CLIENT_ID is required for dashboard_auth_provider=google")
    return GoogleIdTokenVerifier(settings.google_oauth_client_id)


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if settings.dashboard_session_secret is None:
        raise AuthError("dashboard session secret not configured")
    return URLSafeTimedSerializer(settings.dashboard_session_secret.get_secret_value(), salt="eo-session")


def issue_session(settings: Settings, principal: Principal, now: datetime) -> str:
    payload = {
        "c": str(principal.company_id),
        "o": str(principal.owner_id),
        "e": principal.email,
        "iat": int(now.timestamp()),
    }
    return _serializer(settings).dumps(payload)


def read_session(settings: Settings, token: str, now: datetime) -> Principal:
    try:
        data = _serializer(settings).loads(token)
        age = now.timestamp() - int(data["iat"])
        if age > settings.dashboard_session_ttl_min * 60 or age < -MAX_CLOCK_SKEW_S:
            raise AuthError("session expired")
        return Principal(company_id=UUID(data["c"]), owner_id=UUID(data["o"]), email=str(data["e"]))
    except (BadData, KeyError, TypeError, ValueError):
        raise AuthError("invalid session") from None


def owner_by_email(engine: Engine | Connection, email: str) -> Principal | None:
    # Deliberately no company_id filter: this lookup decides which company the principal belongs to.
    # Emails are not unique across companies, so anything but exactly one match is refused.
    stmt = select(OwnerAccount).where(func.lower(OwnerAccount.email) == email.lower()).limit(2)
    with Session(engine) as session:
        owners = session.scalars(stmt).all()
        if len(owners) > 1:
            log.warning("dashboard_login_ambiguous_owner")
            return None
        if not owners:
            return None
        owner = owners[0]
        return Principal(company_id=owner.company_id, owner_id=owner.id, email=owner.email or email)


def owner_matches(engine: Engine | Connection, principal: Principal) -> bool:
    """The session's owner row still exists in its company with the same email (primary-key lookup)."""
    stmt = select(OwnerAccount.email).where(
        OwnerAccount.id == principal.owner_id, OwnerAccount.company_id == principal.company_id
    )
    with Session(engine) as session:
        email = session.scalar(stmt)
    return email is not None and email.lower() == principal.email.lower()


def access_for(engine: Engine | Connection, principal: Principal) -> Access | None:
    """The profile's role and sections from its whitelist row; None when that row was switched off or removed. A
    company that has no whitelist rows at all (an owner who signs in with a Google ID token, never through the
    whitelist) keeps full access; once a company has any row, a session without one is refused."""
    stmt = select(AllowedUser.role, AllowedUser.sections, AllowedUser.is_active).where(
        AllowedUser.company_id == principal.company_id, func.lower(AllowedUser.email) == principal.email.lower()
    )
    with Session(engine) as session:
        row = session.execute(stmt).first()
        if row is None:
            whitelisted = session.scalar(
                select(func.count(AllowedUser.id)).where(AllowedUser.company_id == principal.company_id)
            )
            return None if whitelisted else Access()
    role, sections, is_active = row
    if not is_active:
        return None
    return Access(role=role, sections=None if sections is None else frozenset(sections))


def _secure(settings: Settings) -> bool:
    return settings.env not in ("dev", "test")


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    """The one writer of the session cookie (v1 session exchange and the Google login callback)."""
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.dashboard_session_ttl_min * 60,
        httponly=True,
        samesite="strict",
        secure=_secure(settings),
        domain=settings.dashboard_cookie_domain,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE,
        httponly=True,
        samesite="strict",
        secure=_secure(settings),
        domain=settings.dashboard_cookie_domain,
        path="/",
    )


def email_fingerprint(email: str) -> str:
    """A short hash for logs: enough to correlate attempts, never the address itself."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:8]


def default_dev_principal(engine: Engine | Connection) -> Principal | None:
    """Resolve the default owner account for local dev when the session cookie is absent or invalid."""
    with Session(engine) as session:
        owner = session.scalars(select(OwnerAccount).limit(1)).first()
        if owner:
            return Principal(company_id=owner.company_id, owner_id=owner.id, email=owner.email or "dev@estateos.nl")
    return None


def _dev_bypass(request: Request) -> bool:
    """Local dev only: the SPA runs without a login when `env == "dev"` AND the fake identity provider is configured.
    `test` and `prod` always authenticate. Choosing the Google provider is the operator saying "real logins", so a
    deployment that forgot `ENV=prod` (the default is `dev`) does not fall open."""
    settings = getattr(request.app.state, "settings", None)
    return isinstance(settings, Settings) and settings.env == "dev" and settings.dashboard_auth_provider == "fake"


def _dev_principal_or_401(request: Request) -> Principal:
    if _dev_bypass(request):
        dev_p = default_dev_principal(request.app.state.engine)
        if dev_p:
            return dev_p
    raise HTTPException(status_code=401, detail="not authenticated")


def cookie_principal(request: Request) -> Principal:
    """The signed-cookie checks alone (no I/O): signature, age. 401 when missing or invalid."""
    token = request.cookies.get(COOKIE)
    if not token:
        return _dev_principal_or_401(request)
    try:
        return read_session(cast(Settings, request.app.state.settings), token, datetime.now(UTC))
    except AuthError:
        return _dev_principal_or_401(request)


async def require_principal(request: Request) -> Principal:
    """Signed-cookie checks first, then the owner row is re-read: a removed owner or a changed email ends the
    session at once instead of at cookie expiry."""
    principal = cookie_principal(request)
    if _dev_bypass(request):
        return principal
    if not await run_in_threadpool(owner_matches, request.app.state.engine, principal):
        log.info("dashboard_session_owner_gone", owner_id=str(principal.owner_id))
        raise HTTPException(status_code=401, detail="not authenticated")
    access = await run_in_threadpool(access_for, request.app.state.engine, principal)
    if access is None:
        log.info("dashboard_session_profile_off", owner_id=str(principal.owner_id))
        raise HTTPException(status_code=401, detail="not authenticated")
    return replace(principal, access=access)


def require_csrf(
    request: Request,
    x_estateos_client: Annotated[str | None, Header()] = None,
) -> None:
    if x_estateos_client != CSRF_VALUE and not _dev_bypass(request):
        raise HTTPException(status_code=403, detail="missing client header")


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def require_session(request: Request) -> Principal:
    """Guard of the dashboard routers: a valid session and, for anything that changes state, the client header (the
    cookie is SameSite=Strict, the CORS allow-list is exact, and this header is the third CSRF layer of ADR 0006)."""
    principal = await require_principal(request)
    if request.method not in SAFE_METHODS:
        require_csrf(request, request.headers.get(CSRF_HEADER))
    return principal


class SessionRequest(BaseModel):
    id_token: str


router = APIRouter(tags=["auth"])


@router.post("/auth/session", dependencies=[Depends(require_csrf), Depends(auth_limit)])
async def create_session(body: SessionRequest, request: Request, response: Response) -> dict[str, Any]:
    state = request.app.state
    try:
        email = await run_in_threadpool(state.id_token_verifier.verify, body.id_token)
    except IdentityProviderUnavailableError:
        raise HTTPException(status_code=503, detail="identity provider unavailable") from None
    except AuthError:
        raise HTTPException(status_code=401, detail="invalid id token") from None
    principal = await run_in_threadpool(owner_by_email, state.engine, email)
    if principal is None and _dev_bypass(request):
        # Local development with the fake identity provider: the dev token signs in as the owner that exists (the fake
        # email maps to nobody once a real mailbox has been connected). The same gate as the no-login bypass.
        principal = await run_in_threadpool(default_dev_principal, state.engine)
    if principal is None:
        log.info("dashboard_login_unknown_owner", email_hash=email_fingerprint(email))
        raise HTTPException(status_code=403, detail="not an owner account")
    settings: Settings = state.settings
    set_session_cookie(response, settings, issue_session(settings, principal, datetime.now(UTC)))
    log.info("dashboard_login", email_hash=email_fingerprint(email))
    return {"email": principal.email, "company_id": str(principal.company_id)}


@router.delete("/auth/session", status_code=204, dependencies=[Depends(require_csrf)])
def delete_session(request: Request, response: Response) -> None:
    clear_session_cookie(response, request.app.state.settings)


@router.get("/me")
def me(principal: Annotated[Principal, Depends(require_principal)]) -> dict[str, str]:
    return {
        "email": principal.email,
        "company_id": str(principal.company_id),
        "owner_id": str(principal.owner_id),
    }

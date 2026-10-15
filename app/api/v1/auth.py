"""Dashboard session auth: Google ID token -> signed httpOnly cookie -> `Principal` (company comes from here only)."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.errors import EstateOSError
from app.core.settings import Settings
from app.db.models.tenancy import OwnerAccount

log = structlog.get_logger(__name__)
COOKIE = "eo_session"
CSRF_HEADER = "X-EstateOS-Client"
CSRF_VALUE = "dashboard"
FAKE_DEFAULT_TOKENS = {"test-owner-token": "owner@example.test"}


class AuthError(EstateOSError):
    """Missing, invalid or expired credentials."""


class UnknownOwnerError(AuthError):
    """A verified identity that is not an owner account."""


@dataclass(frozen=True)
class Principal:
    company_id: UUID
    owner_id: UUID
    email: str


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
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        try:
            claims = id_token.verify_oauth2_token(token, google_requests.Request(), self._client_id)
        except ValueError:
            raise AuthError("invalid id token") from None
        email = claims.get("email")
        if not claims.get("email_verified") or not isinstance(email, str):
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
        if now.timestamp() - int(data["iat"]) > settings.dashboard_session_ttl_min * 60:
            raise AuthError("session expired")
        return Principal(company_id=UUID(data["c"]), owner_id=UUID(data["o"]), email=str(data["e"]))
    except (BadSignature, KeyError, TypeError, ValueError):
        raise AuthError("invalid session") from None


def owner_by_email(engine: Engine, email: str) -> Principal | None:
    stmt = select(OwnerAccount).where(func.lower(OwnerAccount.email) == email.lower())
    with Session(engine) as session:
        owner = session.scalars(stmt).first()
        if owner is None or owner.email is None:
            return None
        return Principal(company_id=owner.company_id, owner_id=owner.id, email=owner.email)


def _short(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:8]


def require_principal(request: Request) -> Principal:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    try:
        return read_session(request.app.state.settings, token, datetime.now(UTC))
    except AuthError:
        raise HTTPException(status_code=401, detail="not authenticated") from None


def require_csrf(x_estateos_client: Annotated[str | None, Header()] = None) -> None:
    if x_estateos_client != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="missing client header")


class SessionRequest(BaseModel):
    id_token: str


router = APIRouter(prefix="/api/v1", tags=["auth"])


@router.post("/auth/session")
async def create_session(body: SessionRequest, request: Request, response: Response) -> dict[str, Any]:
    state = request.app.state
    try:
        email = state.id_token_verifier.verify(body.id_token)
    except AuthError:
        raise HTTPException(status_code=401, detail="invalid id token") from None
    principal = await run_in_threadpool(owner_by_email, state.engine, email)
    if principal is None:
        log.info("dashboard_login_unknown_owner", email_hash=_short(email))
        raise HTTPException(status_code=403, detail="not an owner account")
    settings: Settings = state.settings
    response.set_cookie(
        COOKIE,
        issue_session(settings, principal, datetime.now(UTC)),
        max_age=settings.dashboard_session_ttl_min * 60,
        httponly=True,
        samesite="strict",
        secure=settings.env not in ("dev", "test"),
    )
    log.info("dashboard_login", email_hash=_short(email))
    return {"email": principal.email, "company_id": str(principal.company_id)}


@router.delete("/auth/session", status_code=204, dependencies=[Depends(require_csrf)])
def delete_session(response: Response) -> None:
    response.delete_cookie(COOKIE, httponly=True, samesite="strict")


@router.get("/me")
def me(principal: Annotated[Principal, Depends(require_principal)]) -> dict[str, str]:
    return {
        "email": principal.email,
        "company_id": str(principal.company_id),
        "owner_id": str(principal.owner_id),
    }

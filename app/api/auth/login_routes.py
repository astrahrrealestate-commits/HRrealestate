"""Dedicated Platform Login & Whitelist Authentication Routes for EstateOS."""

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote_plus, urlencode
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.auth.oauth_state import LOGIN_COOKIE, MAX_AGE_S, issue_login_state, verify_login_state
from app.api.deps import get_engine, get_settings_dep
from app.api.v1.auth import (
    COOKIE,
    AuthError,
    Principal,
    access_for,
    clear_session_cookie,
    email_fingerprint,
    issue_session,
    owner_matches,
    read_session,
    set_session_cookie,
)
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import AllowedUser, OwnerAccount

router = APIRouter(prefix="/api/auth", tags=["platform_auth"])
log = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint URL, not a secret
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


class AuthMeResponse(BaseModel):
    authenticated: bool
    email: str | None = None
    name: str | None = None
    role: str | None = None
    company_id: str | None = None
    token: str | None = None
    sections: list[str] = []
    is_admin: bool = False


def _login_error(settings: Settings, code: str) -> RedirectResponse:
    """Back to the SPA login page with a fixed error code (never provider text or the caller's input)."""
    response = RedirectResponse(url=f"{settings.frontend_base_url.rstrip('/')}/login?error={quote_plus(code)}")
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return response


@router.get("/login/google/url", summary="Get Google Login Authorization URL")
def get_login_url(settings: Annotated[Settings, Depends(get_settings_dep)], response: Response) -> dict[str, str]:
    """Generates the Google OAuth 2.0 authorization URL for platform sign-in and binds its `state` to this browser."""
    client_id = (settings.google_oauth_client_id or "").strip()
    if not client_id or client_id == "placeholder_client_id":
        raise HTTPException(status_code=500, detail="Google login is not configured on this server.")
    state = issue_login_state(settings)
    params = {
        "client_id": client_id,
        "redirect_uri": settings.google_login_redirect_uri,
        "response_type": "code",
        "scope": " ".join(LOGIN_SCOPES),
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    response.set_cookie(
        LOGIN_COOKIE,
        state,
        max_age=MAX_AGE_S,
        httponly=True,
        samesite="lax",  # the callback is a top-level GET from accounts.google.com: Lax travels, Strict would not
        secure=settings.env == "prod",
        domain=settings.dashboard_cookie_domain,
        path="/",
    )
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


async def _google_email(settings: Settings, code: str) -> tuple[str, str] | str:
    """(verified email, display name) for an authorization code, or a fixed error code."""
    secret = settings.google_oauth_client_secret
    if not settings.google_oauth_client_id or secret is None:
        log.error("auth.login.missing_credentials")
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": secret.get_secret_value(),
                    "redirect_uri": settings.google_login_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code != 200:
                log.error("auth.login.token_exchange_failed", status=token_resp.status_code)
                return "token_exchange_failed"
            user_resp = await client.get(
                GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {token_resp.json().get('access_token')}"}
            )
    except httpx.HTTPError as exc:
        log.error("auth.login.provider_unreachable", error=type(exc).__name__)
        return "provider_unreachable"
    if user_resp.status_code != 200:
        log.error("auth.login.userinfo_failed", status=user_resp.status_code)
        return "profile_unavailable"
    info = user_resp.json()
    email = (info.get("email") or "").strip().lower()
    if not email:
        return "no_email"
    if info.get("email_verified") is not True:
        return "unverified_email"
    return email, info.get("name") or info.get("given_name") or email.split("@")[0].title()


def _owner_for(session: Session, allowed: AllowedUser, email: str, name: str) -> OwnerAccount:
    """The owner row of this person in the whitelist entry's own company: found by email, else created. Another
    person's row is never reused or rewritten (a newly whitelisted user must not become the first owner)."""
    owner = session.scalars(
        select(OwnerAccount).where(
            OwnerAccount.company_id == allowed.company_id, func.lower(OwnerAccount.email) == email
        )
    ).first()
    if owner is None:
        owner_id = uuid4()
        owner = OwnerAccount(
            id=owner_id,
            company_id=allowed.company_id,
            display_name=name,
            whatsapp_e164=f"web:{owner_id.hex[:12]}",  # unique placeholder: this person has no WhatsApp number on file
            email=email,
        )
        session.add(owner)
        session.flush()
    elif name:
        owner.display_name = name
    return owner


@router.get("/login/google/callback", summary="Google Login OAuth Callback")
async def login_callback(
    request: Request,
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    code: str = Query(default="", description="Authorization code from Google"),
    state: str = Query(default="", description="Signed state, equal to the browser's login cookie"),
) -> RedirectResponse:
    """Exchanges the code for a verified email, checks the whitelist, and starts the session for the whitelist
    entry's own company."""
    try:
        verify_login_state(settings, state, request.cookies.get(LOGIN_COOKIE))
    except AuthError:
        log.warning("auth.login.invalid_state")
        return _login_error(settings, "invalid_state")
    if not code:
        return _login_error(settings, "no_code")

    identity = await _google_email(settings, code)
    if isinstance(identity, str):
        return _login_error(settings, identity)
    email, name = identity

    # The whitelist is the gatekeeper (allowed_users); its row names the company the person may enter.
    with Session(engine) as session, session.begin():
        rows = session.scalars(
            select(AllowedUser).where(func.lower(AllowedUser.email) == email, AllowedUser.is_active.is_(True))
        ).all()
        if not rows:
            log.warning("auth.login.access_denied_not_whitelisted", email_hash=email_fingerprint(email))
            return _login_error(settings, "access_denied")
        if len(rows) > 1:  # never guess which company a shared address means
            log.warning("auth.login.ambiguous_address", email_hash=email_fingerprint(email), companies=len(rows))
            return _login_error(settings, "ambiguous_account")
        allowed = rows[0]
        owner = _owner_for(session, allowed, email, name)
        principal = Principal(company_id=allowed.company_id, owner_id=owner.id, email=email)
        session_token = issue_session(settings, principal, datetime.now(UTC))
        log.info("auth.login.success", email_hash=email_fingerprint(email), role=allowed.role)

    redirect_url = f"{settings.frontend_base_url.rstrip('/')}/?session_token={session_token}"
    response = RedirectResponse(url=redirect_url, status_code=303)
    set_session_cookie(response, settings, session_token)
    response.delete_cookie(LOGIN_COOKIE, path="/")
    return response


@router.get("/me", response_model=AuthMeResponse, summary="Get Current Authenticated User")
def get_current_user_profile(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    request: Request,
) -> AuthMeResponse:
    """The signed-in owner, with the same checks as the dashboard guard: a valid session whose owner row still exists
    with the same email. Supports cookie, X-Session-Token, or Bearer auth. Answers `authenticated=false` when absent."""
    token = request.cookies.get(COOKIE) or request.headers.get("X-Session-Token")
    if not token:
        auth_h = request.headers.get("Authorization", "")
        if auth_h.startswith("Bearer "):
            token = auth_h[7:].strip()
    if not token:
        return AuthMeResponse(authenticated=False)
    try:
        principal = read_session(settings, token, datetime.now(UTC))
    except AuthError:
        return AuthMeResponse(authenticated=False)
    if not owner_matches(engine, principal):
        return AuthMeResponse(authenticated=False)
    access = access_for(engine, principal)
    if access is None:  # the profile was switched off: the session ends here, as it does on every other route
        return AuthMeResponse(authenticated=False)

    with Session(engine) as session:
        allowed = session.scalars(
            select(AllowedUser).where(
                AllowedUser.company_id == principal.company_id,
                func.lower(AllowedUser.email) == principal.email.lower(),
                AllowedUser.is_active.is_(True),
            )
        ).first()
        owner_name = session.scalar(
            select(OwnerAccount.display_name).where(
                OwnerAccount.id == principal.owner_id, OwnerAccount.company_id == principal.company_id
            )
        )
        # The whitelist's name wins; otherwise the name Google gave at sign-in; the email prefix is the last resort.
        display_name = allowed.display_name if allowed else owner_name or principal.email.split("@")[0].title()

    return AuthMeResponse(
        authenticated=True,
        email=principal.email,
        name=display_name,
        role=access.role,
        company_id=str(principal.company_id),
        token=token,
        sections=access.visible_sections(),
        is_admin=access.is_admin,
    )


@router.post("/logout", summary="Log Out & Clear Session")
def logout(response: Response, settings: Annotated[Settings, Depends(get_settings_dep)]) -> dict[str, bool]:
    """Clears the session cookie."""
    clear_session_cookie(response, settings)
    return {"success": True}

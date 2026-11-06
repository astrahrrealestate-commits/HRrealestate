"""Dedicated Platform Login & Whitelist Authentication Routes for EstateOS."""

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import quote_plus, urlencode
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_settings_dep
from app.api.v1.auth import COOKIE, Principal, issue_session, read_session
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import AllowedUser, Company, OwnerAccount

router = APIRouter(prefix="/api/auth", tags=["platform_auth"])
log = get_logger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
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


@router.get("/login/google/url", summary="Get Google Login Authorization URL")
def get_login_url(settings: Settings = Depends(get_settings_dep)) -> dict[str, str]:
    """Generates the Google OAuth 2.0 authorization URL for platform sign-in."""
    import os
    client_id = (settings.google_oauth_client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    if not client_id or client_id == "placeholder_client_id":
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_OAUTH_CLIENT_ID is not configured in .env. Please check realestateos/.env and restart the backend server."
        )
    # Port 8000 for FastAPI callback
    redirect_uri = "http://localhost:8000/api/auth/login/google/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(LOGIN_SCOPES),
        "access_type": "online",
        "prompt": "select_account",
        "state": "estateos_login_" + uuid4().hex[:12],
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return {"url": url}


@router.get("/login/google/callback", summary="Google Login OAuth Callback")
async def login_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(default="", description="CSRF state token"),
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    """Exchanges Google authorization code for identity tokens, verifies database whitelist, and mints session."""
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    redirect_uri = "http://localhost:8000/api/auth/login/google/callback"

    if not client_id or not client_secret:
        log.error("auth.login.missing_credentials")
        return RedirectResponse(
            url="http://localhost:3000/login?error=" + quote_plus("Google OAuth client is not configured in .env")
        )

    # 1. Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret.get_secret_value() if hasattr(client_secret, "get_secret_value") else str(client_secret),
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )

        if token_resp.status_code != 200:
            log.error("auth.login.token_exchange_failed", status=token_resp.status_code, body=token_resp.text)
            return RedirectResponse(
                url="http://localhost:3000/login?error=" + quote_plus("Google token exchange failed. Please try again.")
            )

        tokens = token_resp.json()
        access_token = tokens.get("access_token")

        # 2. Fetch verified Google user info
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if user_resp.status_code != 200:
            log.error("auth.login.userinfo_failed", status=user_resp.status_code)
            return RedirectResponse(
                url="http://localhost:3000/login?error=" + quote_plus("Could not verify Google profile details.")
            )

        user_info = user_resp.json()
        email = (user_info.get("email") or "").strip().lower()
        name = user_info.get("name") or user_info.get("given_name") or email.split("@")[0].title()

    except Exception as exc:
        log.error("auth.login.callback_exception", error=str(exc))
        return RedirectResponse(url="http://localhost:3000/login?error=" + quote_plus(str(exc)))

    if not email:
        return RedirectResponse(url="http://localhost:3000/login?error=" + quote_plus("No email returned by Google"))

    # 3. THE WHITELIST CHECK (Strict gatekeeper against PostgreSQL allowed_users)
    with Session(engine) as session, session.begin():
        allowed = session.scalars(
            select(AllowedUser).where(
                func.lower(AllowedUser.email) == email,
                AllowedUser.is_active == True,  # noqa: E712
            )
        ).first()

        if not allowed:
            log.warning("auth.login.access_denied_not_whitelisted", email=email)
            return RedirectResponse(
                url=f"http://localhost:3000/login?error=access_denied&email={quote_plus(email)}"
            )

        # 4. Resolve or update OwnerAccount
        company = session.scalars(select(Company).limit(1)).first()
        company_id = company.id if company else allowed.company_id

        owner = session.scalars(
            select(OwnerAccount).where(func.lower(OwnerAccount.email) == email)
        ).first()

        if not owner:
            owner = session.scalars(
                select(OwnerAccount).where(OwnerAccount.company_id == company_id).limit(1)
            ).first()

        if not owner:
            owner = OwnerAccount(
                company_id=company_id,
                display_name=name,
                whatsapp_e164="+31600000000",
                email=email,
            )
            session.add(owner)
            session.flush()
        else:
            owner.email = email
            if name:
                owner.display_name = name

        principal = Principal(
            company_id=company_id,
            owner_id=owner.id,
            email=email,
        )

        # 5. Mint cryptographically signed session cookie
        now = datetime.now(UTC)
        session_token = issue_session(settings, principal, now)
        log.info("auth.login.success", email=email, role=allowed.role)

    # 6. Set httpOnly session cookie and redirect to platform dashboard
    response = RedirectResponse(url="http://localhost:3000/", status_code=303)
    response.set_cookie(
        key=COOKIE,
        value=session_token,
        max_age=settings.dashboard_session_ttl_min * 60,
        httponly=True,
        samesite="lax",
        secure=settings.env == "prod",
        path="/",
    )
    return response


@router.get("/me", response_model=AuthMeResponse, summary="Get Current Authenticated User")
def get_current_user_profile(
    request: Request,
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings_dep),
) -> AuthMeResponse:
    """Returns current active user session profile from signed cookie."""
    token = request.cookies.get(COOKIE)
    if not token:
        # Check authorization header fallback
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr.replace("Bearer ", "").strip()

    if not token:
        return AuthMeResponse(authenticated=False)

    try:
        now = datetime.now(UTC)
        principal = read_session(settings, token, now)
    except Exception:
        return AuthMeResponse(authenticated=False)

    with Session(engine) as session:
        allowed = session.scalars(
            select(AllowedUser).where(
                func.lower(AllowedUser.email) == principal.email.lower(),
                AllowedUser.is_active == True,  # noqa: E712
            )
        ).first()

        display_name = allowed.display_name if allowed else principal.email.split("@")[0].title()
        role = allowed.role if allowed else "manager"

    return AuthMeResponse(
        authenticated=True,
        email=principal.email,
        name=display_name,
        role=role,
        company_id=str(principal.company_id),
    )


@router.post("/logout", summary="Log Out & Clear Session")
def logout(response: Response, settings: Settings = Depends(get_settings_dep)) -> dict[str, bool]:
    """Clears the session cookie."""
    response.delete_cookie(
        key=COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.env == "prod",
        path="/",
    )
    return {"success": True}


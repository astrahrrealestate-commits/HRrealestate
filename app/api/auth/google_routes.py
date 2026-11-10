"""Google OAuth & Multi-Service Integration Routes.

Provides endpoints to connect, switch, or disconnect Google Workspace
(Gmail, Google Calendar, Google Drive) directly from the Connections modal.

`/url`, `/status` and `/disconnect` need the dashboard session. The callback is a cross-site redirect from Google that
carries no cookie, so it is bound to the owner by the signed `state` that `/url` issued (`oauth_state`): the company and
owner it names are the only rows the callback may change.
"""

from typing import Annotated, Any
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.auth.oauth_state import ConnectState, issue_state, read_state
from app.api.deps import get_engine, get_settings_dep
from app.api.v1.auth import AuthError, Principal, require_session
from app.channels import google_auth, registry
from app.channels.google_auth import GoogleConnectionStatus
from app.contracts import Channel
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ChannelAccount, GmailSyncState, OwnerAccount

router = APIRouter(prefix="/api/auth/google", tags=["google_auth"])
log = get_logger(__name__)


@router.get("/url")
def get_oauth_url(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
    return_to: str = Query(default="/", description="Path to return to after auth flow"),
) -> dict[str, str]:
    """Returns the Google authorization URL; its `state` is signed for this owner and company."""
    return {"url": google_auth.get_authorization_url(settings, state=issue_state(settings, principal, return_to))}


@router.get("/status")
def get_status(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _principal: Annotated[Principal, Depends(require_session)],
) -> GoogleConnectionStatus:
    """Returns current connection status, email, name, avatar picture, and active scopes."""
    return google_auth.get_connection_status(settings)


def connect_mailbox(engine: Engine, state: ConnectState, email: str, name: str | None) -> None:
    """Point the state's company at the Google mailbox and make it the state's owner's login email. Only the rows of
    `state.company_id` and `state.owner_id` change; a fresh mailbox starts with a fresh Gmail sync state."""
    with Session(engine) as session:
        channel = session.scalars(
            select(ChannelAccount).where(
                ChannelAccount.company_id == state.company_id, ChannelAccount.channel == Channel.gmail
            )
        ).first()
        if channel:
            log.info("api.auth.google.channel_switched", company_id=str(state.company_id))
            channel.address = email
            sync_state = session.get(GmailSyncState, channel.id)
            if sync_state:
                session.delete(sync_state)
        else:
            session.add(ChannelAccount(company_id=state.company_id, channel=Channel.gmail, address=email))
        owner = session.scalars(
            select(OwnerAccount).where(OwnerAccount.id == state.owner_id, OwnerAccount.company_id == state.company_id)
        ).first()
        if owner:
            owner.email = email
            if name:
                owner.display_name = name
        session.commit()


def _clear_mailbox_cache() -> None:
    """Invalidate the in-memory mailbox cache so the app talks to the new mailbox immediately."""
    cache = getattr(registry._local_mailboxes, "cache", None)
    if cache is not None:
        cache.clear()


@router.get("/callback")
async def oauth_callback(
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    code: str | None = Query(default=None, description="Authorization code from Google"),
    error: str | None = Query(default=None, description="Error if user cancelled or denied consent"),
    state: str = Query(default="", description="Signed state issued by /url"),
) -> RedirectResponse:
    """Handles OAuth callback, exchanges code for permanent tokens, and updates DB atomically."""
    try:
        verified = read_state(settings, state)
    except AuthError:
        log.warning("api.auth.google.invalid_state")
        raise HTTPException(status_code=403, detail="invalid or expired state") from None

    back = f"{settings.frontend_base_url.rstrip('/')}{verified.return_to}?connections=open"

    if error:
        log.warning("api.auth.google.oauth_denied", error=error)
        return RedirectResponse(url=f"{back}&google_error=" + quote_plus(error))
    if not code:
        log.error("api.auth.google.missing_code")
        return RedirectResponse(url=f"{back}&google_error=" + quote_plus("No authorization code received from Google."))

    try:
        creds = await google_auth.exchange_code_for_tokens(settings, code)
    except Exception as exc:
        log.error("api.auth.google.callback_failed", error=type(exc).__name__)
        return RedirectResponse(url=f"{back}&google_error=" + quote_plus("Google token exchange failed."))

    email = (creds.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse(url=f"{back}&google_error=no_email_returned")

    connect_mailbox(engine, verified, email, creds.get("name"))
    _clear_mailbox_cache()
    return RedirectResponse(url=f"{back}&google_connected=success&email=" + quote_plus(email))


@router.post("/disconnect")
def disconnect_account(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    _principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Disconnects the Google account, unlinks credentials, and deactivates channel accounts."""
    if not google_auth.disconnect_owner(settings):
        raise HTTPException(status_code=500, detail="Failed to remove Google credentials")
    _clear_mailbox_cache()
    return {"success": True, "message": "Google account successfully disconnected."}

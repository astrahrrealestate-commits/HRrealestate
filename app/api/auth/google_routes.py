"""Google OAuth & Multi-Service Integration Routes.

Provides endpoints for Harjot to connect, switch, or disconnect his unified Google account
(Gmail, Google Calendar, Google Drive) directly from Settings.
"""

from typing import Any
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine, get_settings_dep
from app.channels import google_auth, registry
from app.channels.google_auth import GoogleConnectionStatus
from app.contracts import Channel
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ChannelAccount, Company, GmailSyncState, OwnerAccount

router = APIRouter(prefix="/api/auth/google", tags=["google_auth"])
log = get_logger(__name__)


@router.get("/url")
def get_oauth_url(settings: Settings = Depends(get_settings_dep)) -> dict[str, str]:
    """Returns Google authorization URL for frontend 'Connect Google' button."""
    url = google_auth.get_authorization_url(settings)
    return {"url": url}


@router.get("/status")
def get_status(settings: Settings = Depends(get_settings_dep)) -> GoogleConnectionStatus:
    """Returns current connection status, email, name, avatar picture, and active scopes."""
    return google_auth.get_connection_status(settings)


@router.get("/callback")
async def oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings_dep),
) -> RedirectResponse:
    """Handles OAuth callback, exchanges code for permanent tokens, and updates DB atomically."""
    try:
        creds = await google_auth.exchange_code_for_tokens(settings, code)
    except Exception as exc:
        log.error("api.auth.google.callback_failed", error=str(exc))
        return RedirectResponse(url="http://localhost:3000/settings?google_error=" + quote_plus(str(exc)))

    email = (creds.get("email") or "").strip().lower()
    name = creds.get("name") or "Harjot Singh"

    if not email:
        return RedirectResponse(url="http://localhost:3000/settings?google_error=no_email_returned")

    # Atomic DB update: synchronize channel_accounts, owner_accounts, and reset sync state
    with Session(engine) as session:
        company = session.scalars(select(Company).limit(1)).first()
        company_id = company.id if company else None

        if company_id:
            # 1. Update or create Gmail ChannelAccount
            ch_acc = session.scalars(
                select(ChannelAccount).where(
                    ChannelAccount.company_id == company_id,
                    ChannelAccount.channel == Channel.gmail,
                )
            ).first()

            if ch_acc:
                old_addr = ch_acc.address
                ch_acc.address = email
                log.info("api.auth.google.channel_switched", old=old_addr, new=email)
                # Reset sync state so new mailbox starts fresh sync
                sync_state = session.get(GmailSyncState, ch_acc.id)
                if sync_state:
                    session.delete(sync_state)
            else:
                ch_acc = ChannelAccount(company_id=company_id, channel=Channel.gmail, address=email)
                session.add(ch_acc)

            # 2. Update OwnerAccount
            owner = session.scalars(
                select(OwnerAccount).where(OwnerAccount.company_id == company_id).limit(1)
            ).first()
            if owner:
                owner.email = email
                if name:
                    owner.display_name = name
                log.info("api.auth.google.owner_email_updated", email=email, name=name)

            session.commit()

        # Invalidate in-memory mailbox cache so the app talks to the new mailbox immediately
        cache = getattr(registry._local_mailboxes, "cache", None)
        if cache is not None:
            cache.clear()

    return RedirectResponse(
        url="http://localhost:3000/settings?google_connected=success&email=" + quote_plus(email)
    )


@router.post("/disconnect")
def disconnect_account(
    engine: Engine = Depends(get_engine),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Disconnects the Google account and unlinks credentials."""
    ok = google_auth.disconnect_owner(settings)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to remove Google credentials")

    # Clear in-memory cache
    cache = getattr(registry._local_mailboxes, "cache", None)
    if cache is not None:
        cache.clear()

    return {"success": True, "message": "Google account successfully disconnected."}

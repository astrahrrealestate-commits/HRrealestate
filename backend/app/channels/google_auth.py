"""Unified Google OAuth Manager for Single-Owner (Harjot).

Handles one-click OAuth authorization for Gmail, Google Calendar, and Google Drive simultaneously.
Produces a long-lived credentials file with automatic refresh token support.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from app.channels import google_store
from app.core.logging import get_logger
from app.core.settings import Settings

log = get_logger(__name__)

UNIFIED_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
]

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint, not a credential
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


class GoogleConnectionStatus(BaseModel):
    connected: bool
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    scopes: list[str] = []
    connected_at: str | None = None


def get_credentials_path(settings: Settings) -> Path:
    """The local copy of Harjot's unified Google credentials, brought up to date with the shared one (google_store)."""
    return google_store.refresh(settings)


def get_authorization_url(settings: Settings, state: str = "estateos_owner_auth") -> str:
    """Generates the Google OAuth 2.0 authorization URL requesting permanent offline access."""

    client_id = (settings.google_oauth_client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    if not client_id:
        client_id = "placeholder_client_id"
    redirect_uri = settings.google_oauth_redirect_uri or "http://localhost:8000/api/auth/google/callback"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(UNIFIED_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(settings: Settings, code: str) -> dict[str, Any]:
    """Exchanges authorization code for tokens, retrieves user profile, and constructs credentials dict."""

    client_id = (settings.google_oauth_client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or "").strip()
    client_secret = (
        settings.google_oauth_client_secret.get_secret_value()
        if settings.google_oauth_client_secret
        else os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    ).strip()
    redirect_uri = settings.google_oauth_redirect_uri or "http://localhost:8000/api/auth/google/callback"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Exchange authorization code for tokens
        token_resp = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            log.error("google_auth.token_exchange_failed", status=token_resp.status_code)
            raise ValueError(f"Failed to exchange Google OAuth code (HTTP {token_resp.status_code})")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        # 2. Query userinfo to get verified email, name, and profile picture
        userinfo_resp = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json() if userinfo_resp.status_code == 200 else {}
        email = (userinfo.get("email") or "").lower()
        name = userinfo.get("name") or "Harjot Singh"
        picture = userinfo.get("picture")

        # If refresh_token wasn't returned on re-auth, try to keep existing refresh_token
        if not refresh_token:
            existing = await asyncio.to_thread(load_owner_credentials, settings)  # S3 read: off the event loop
            if existing and existing.get("refresh_token"):
                refresh_token = existing["refresh_token"]

        credentials_dict = {
            "token": access_token,
            "refresh_token": refresh_token,
            "token_uri": TOKEN_URL,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": UNIFIED_SCOPES,
            "email": email,
            "name": name,
            "picture": picture,
        }

        # 3. Save to disk in format standard for google.oauth2.credentials.Credentials
        await asyncio.to_thread(save_owner_credentials, settings, credentials_dict)  # S3 write: off the event loop
        return credentials_dict


def save_owner_credentials(settings: Settings, credentials_dict: dict[str, Any]) -> Path:
    """Saves the credentials where every process finds them (the shared copy on S3, and the local file)."""
    path = google_store.publish(settings, credentials_dict)
    log.info("google_auth.credentials_saved")
    return path


def load_owner_credentials(settings: Settings) -> dict[str, Any] | None:
    """Loads existing unified Google credentials if available."""
    path = get_credentials_path(settings)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except Exception as exc:
        log.warning("google_auth.load_credentials_failed", error=str(exc))
        return None


def get_connection_status(settings: Settings) -> GoogleConnectionStatus:
    """Returns the current connection status of Harjot's Google account."""
    data = load_owner_credentials(settings)
    if not data or not data.get("email"):
        return GoogleConnectionStatus(connected=False)
    return GoogleConnectionStatus(
        connected=True,
        email=data.get("email"),
        name=data.get("name") or "Harjot Singh",
        picture=data.get("picture"),
        scopes=data.get("scopes") or UNIFIED_SCOPES,
    )


def _revoke(credentials: dict[str, Any] | None) -> None:
    """Revoke the grant at Google: earlier token versions stay in the versioned bucket, and a revoked grant makes
    every one of them worthless. Best effort; a failure is logged and the local disconnect goes ahead."""
    token = (credentials or {}).get("refresh_token") or (credentials or {}).get("token")
    if not token:
        return
    try:
        response = httpx.post(REVOKE_URL, data={"token": token}, timeout=10.0)
    except httpx.HTTPError as exc:
        log.warning("google_auth.revoke_failed", error=type(exc).__name__)
        return
    if response.status_code != 200:
        log.warning("google_auth.revoke_failed", status=response.status_code)


def disconnect_owner(settings: Settings) -> bool:
    """Disconnects the active Google account: revokes the grant at Google, then removes the saved credentials,
    shared copy included."""
    _revoke(load_owner_credentials(settings))
    try:
        google_store.withdraw(settings)
    except Exception as exc:
        log.error("google_auth.disconnect_failed", error=type(exc).__name__)
        return False
    log.info("google_auth.disconnected")
    return True

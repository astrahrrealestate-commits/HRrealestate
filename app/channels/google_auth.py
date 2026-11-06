"""Unified Google OAuth Manager for Single-Owner (Harjot).

Handles one-click OAuth authorization for Gmail, Google Calendar, and Google Drive simultaneously.
Produces a long-lived credentials file with automatic refresh token support.
"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

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


class GoogleConnectionStatus(BaseModel):
    connected: bool
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    scopes: list[str] = []
    connected_at: str | None = None


def get_credentials_path(settings: Settings) -> Path:
    """Returns the persistent path for Harjot's unified Google credentials."""
    creds_dir = Path(".data/credentials")
    creds_dir.mkdir(parents=True, exist_ok=True)
    return creds_dir / "google_owner.json"


def get_authorization_url(settings: Settings, state: str = "estateos_owner_auth") -> str:
    """Generates the Google OAuth 2.0 authorization URL requesting permanent offline access."""
    import os

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
    import os

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
            log.error("google_auth.token_exchange_failed", status=token_resp.status_code, body=token_resp.text)
            raise ValueError(f"Failed to exchange Google OAuth code: {token_resp.text}")

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
            existing = load_owner_credentials(settings)
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
        save_owner_credentials(settings, credentials_dict)
        return credentials_dict


def save_owner_credentials(settings: Settings, credentials_dict: dict[str, Any]) -> Path:
    """Saves credentials dictionary to unified path."""
    path = get_credentials_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(credentials_dict, f, indent=2)
    log.info("google_auth.credentials_saved", path=str(path), email=credentials_dict.get("email"))
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


def disconnect_owner(settings: Settings) -> bool:
    """Disconnects the active Google account by removing the saved credentials."""
    path = get_credentials_path(settings)
    if path.exists():
        try:
            path.unlink()
            log.info("google_auth.disconnected", path=str(path))
            return True
        except Exception as exc:
            log.error("google_auth.disconnect_failed", error=str(exc))
            return False
    return True

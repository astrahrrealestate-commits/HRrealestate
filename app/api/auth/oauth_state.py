"""Signed `state` of the Gmail connect flow: it binds the Google callback to the owner who started it.

The callback is a cross-site redirect from Google, so the SameSite=Strict session cookie does not travel with it.
The state replaces the cookie: `/api/auth/google/url` (authenticated) issues it, the callback accepts only a state
that verifies and is younger than `MAX_AGE_S`, and the company and owner it names are the only ones the callback may
touch. Without it anyone could register their own mailbox, and the owner's login email, with a forged callback.
A separate salt keeps a session cookie from ever verifying as a state.
"""

import secrets
from dataclasses import dataclass
from uuid import UUID

from itsdangerous import BadData, URLSafeTimedSerializer

from app.api.v1.auth import AuthError, Principal
from app.core.settings import Settings

MAX_AGE_S = 600
SALT = "eo-google-connect"


@dataclass(frozen=True)
class ConnectState:
    company_id: UUID
    owner_id: UUID
    return_to: str


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if settings.dashboard_session_secret is None:
        raise AuthError("dashboard session secret not configured")
    return URLSafeTimedSerializer(settings.dashboard_session_secret.get_secret_value(), salt=SALT)


def clean_return(return_to: str) -> str:
    """A path on the SPA, never an absolute or protocol-relative URL (`//evil.test` is an open redirect)."""
    return return_to if return_to.startswith("/") and not return_to.startswith("//") else "/"


def issue_state(settings: Settings, principal: Principal, return_to: str) -> str:
    payload = {
        "c": str(principal.company_id),
        "o": str(principal.owner_id),
        "r": clean_return(return_to),
        "n": secrets.token_urlsafe(8),
    }
    return _serializer(settings).dumps(payload)


def read_state(settings: Settings, token: str) -> ConnectState:
    try:
        data = _serializer(settings).loads(token, max_age=MAX_AGE_S)
        return ConnectState(UUID(data["c"]), UUID(data["o"]), clean_return(str(data["r"])))
    except (BadData, KeyError, TypeError, ValueError):
        raise AuthError("invalid state") from None

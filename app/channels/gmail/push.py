"""Gmail Pub/Sub push verification: OIDC bearer token (alg, issuer, audience, service-account email) + envelope.

Google mode and local mode (fake provider, simulator) share one verification routine; they differ only in where the
signing certs come from (Google's endpoint with a TTL cache vs dev certs on disk). Every failure — including forged
headers that make the JWT library raise unexpected types — becomes `PushRejectedError` (→ 401), never a 500.
"""

import base64
import binascii
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import google.auth.exceptions
import google.auth.jwt
import requests

from app.channels.gmail.ports import PushNotice
from app.core.errors import PushRejectedError

ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
DEV_AUDIENCE = "estateos-dev-gmail-push"  # fake provider defaults (simulator signs with dev keys)
DEV_SERVICE_ACCOUNT = "dev-pubsub@estateos.test"
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
MAX_PUSH_BYTES = 64 * 1024
CLOCK_SKEW_SEC = 10
_MAX_AGE = re.compile(r"max-age=(\d+)")

CertsProvider = Callable[[bool], Mapping[str, str]]  # (force_refresh) -> {kid: cert PEM}


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 8192:
        raise PushRejectedError("missing bearer token")
    return authorization.removeprefix("Bearer ").strip()


def _header(token: str) -> dict[str, Any]:
    """Unverified JWT header, only to refuse anything but RS256 with a key id before verification."""
    try:
        segment = token.split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
    except (ValueError, IndexError, binascii.Error) as exc:
        raise PushRejectedError("malformed token header") from exc
    if not isinstance(header, dict) or header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise PushRejectedError("unsupported token algorithm or missing key id")
    return header


def _check_claims(claims: Mapping[str, Any], service_account: str) -> None:
    if claims.get("iss") not in ISSUERS:
        raise PushRejectedError("unexpected token issuer")
    if claims.get("email") != service_account or claims.get("email_verified") is not True:
        raise PushRejectedError("push token not issued for the expected service account")


def parse_push_body(body: bytes) -> PushNotice:
    if len(body) > MAX_PUSH_BYTES:
        raise PushRejectedError("push body too large")
    try:
        envelope = json.loads(body)
        message = envelope["message"]
        data = json.loads(base64.b64decode(message["data"], validate=True))
        email, history = str(data["emailAddress"]).lower(), str(data["historyId"])
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise PushRejectedError("malformed Pub/Sub envelope") from exc
    if not (history.isascii() and history.isdigit() and len(history) <= 19) or "@" not in email:
        raise PushRejectedError("malformed Gmail notification data")
    return PushNotice(email=email, history_id=int(history), message_id=str(message.get("messageId") or "") or None)


class PushVerifier:
    def __init__(self, audience: str, service_account: str, certs: CertsProvider) -> None:
        self._audience = audience
        self._service_account = service_account
        self._certs = certs

    def verify(self, authorization: str | None, body: bytes) -> PushNotice:
        token = _bearer(authorization)
        kid = _header(token)["kid"]
        certs = self._certs(False)
        if kid not in certs:
            certs = self._certs(True)  # key rotation or dev keys created after startup
        if kid not in certs:
            raise PushRejectedError("unknown signing key")
        try:
            claims = google.auth.jwt.decode(
                token, certs={kid: certs[kid]}, audience=self._audience, clock_skew_in_seconds=CLOCK_SKEW_SEC
            )
        except (ValueError, TypeError, google.auth.exceptions.GoogleAuthError) as exc:
            raise PushRejectedError("push token verification failed") from exc
        _check_claims(claims, self._service_account)
        return parse_push_body(body)


class GoogleCerts:
    """Google's OIDC certs with an in-process TTL cache honouring Cache-Control max-age."""

    def __init__(self, url: str = GOOGLE_CERTS_URL, session: requests.Session | None = None) -> None:
        self._url = url
        self._session = session or requests.Session()
        self._lock = threading.Lock()
        self._certs: dict[str, str] = {}
        self._expires = 0.0

    def __call__(self, force_refresh: bool) -> Mapping[str, str]:
        with self._lock:
            if force_refresh or not self._certs or time.monotonic() >= self._expires:
                self._refresh()
            return dict(self._certs)

    def _refresh(self) -> None:
        try:
            response = self._session.get(self._url, timeout=5)
            response.raise_for_status()
            certs = response.json()
        except (requests.RequestException, ValueError) as exc:
            if self._certs:
                return  # keep serving the last good certs
            raise PushRejectedError("could not fetch Google signing certs") from exc
        max_age = _MAX_AGE.search(response.headers.get("Cache-Control", ""))
        self._certs = {str(k): str(v) for k, v in certs.items()}
        self._expires = time.monotonic() + (int(max_age.group(1)) if max_age else 3600)


def dir_certs(directory: Path) -> CertsProvider:
    """Dev certs from disk, re-read on demand (the simulator may create them after the API started)."""
    cache: dict[str, str] = {}

    def provider(force_refresh: bool) -> Mapping[str, str]:
        if force_refresh or not cache:
            path = directory / "certs.json"
            cache.clear()
            cache.update(json.loads(path.read_text()) if path.exists() else {})
        return dict(cache)

    return provider


def google_push_verifier(audience: str, service_account: str, certs: CertsProvider | None = None) -> PushVerifier:
    return PushVerifier(audience, service_account, certs or GoogleCerts())


def local_push_verifier(directory: Path, audience: str, service_account: str) -> PushVerifier:
    return PushVerifier(audience, service_account, dir_certs(directory))

"""WhatsApp webhook authentication: body HMAC-SHA256 per provider, and the subscription handshake.

Meta Cloud API signs with the app secret in `X-Hub-Signature-256: sha256=<hex>`. 360dialog signs with the partner
platform secret in `x-360dialog-signature: <hex>`. Either way the secret is `WHATSAPP_APP_SECRET`.
"""

import hashlib
import hmac
from dataclasses import dataclass

from app.core.errors import WebhookRejectedError

MAX_WEBHOOK_BYTES = 4 * 1024 * 1024  # Meta batches can reach ~3 MB; routes answer 413 above this before reading on
# Fake-provider defaults (dev/simulator only; prod requires real values — see core.startup).
DEV_APP_SECRET = "estateos-dev-whatsapp-app-secret"  # noqa: S105 — fake provider only; prod refuses fakes
DEV_VERIFY_TOKEN = "estateos-dev-verify-token"  # noqa: S105 — fake provider only


@dataclass(frozen=True)
class SignatureScheme:
    header: str  # lower-case HTTP header name
    prefix: str
    any_case: bool = False  # hex case not documented by the provider: compare case-insensitively


META = SignatureScheme("x-hub-signature-256", "sha256=")
DIALOG360 = SignatureScheme("x-360dialog-signature", "", any_case=True)


def signature_scheme(provider: str) -> SignatureScheme:
    """The fake provider and SendZen sign like Meta (HMAC-SHA256 in x-hub-signature-256)."""
    return DIALOG360 if provider == "360dialog" else META


def sign_body(secret: str, body: bytes, scheme: SignatureScheme = META) -> str:
    """Signature header value for a body (used by tests and the dev simulator)."""
    return scheme.prefix + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _same(a: str, b: str) -> bool:
    """Constant-time compare that cannot raise on non-ASCII input (headers arrive latin-1 decoded)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogateescape"), b.encode("utf-8", "surrogateescape"))


def verify_signature(body: bytes, header: str | None, secret: str, scheme: SignatureScheme = META) -> None:
    if not secret:
        raise WebhookRejectedError("app secret not configured")
    if header and scheme.any_case:
        header = header.strip().lower()
    if not header or not header.startswith(scheme.prefix):
        raise WebhookRejectedError(f"missing or malformed {scheme.header}")
    if not _same(sign_body(secret, body, scheme), header):
        raise WebhookRejectedError("signature mismatch")


def verify_handshake(mode: str | None, token: str | None, challenge: str | None, *, expected_token: str) -> str:
    if not expected_token:
        raise WebhookRejectedError("verify token not configured")
    if mode != "subscribe" or token is None or not _same(token, expected_token):
        raise WebhookRejectedError("webhook verification handshake failed")
    if not challenge or not challenge.isascii() or not challenge.isdigit():
        raise WebhookRejectedError("handshake challenge must be numeric")
    return challenge

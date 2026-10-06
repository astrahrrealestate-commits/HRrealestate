"""WhatsApp webhook authentication: X-Hub-Signature-256 HMAC and the subscription handshake."""

import hashlib
import hmac

from app.core.errors import WebhookRejectedError

MAX_WEBHOOK_BYTES = 4 * 1024 * 1024  # Meta batches can reach ~3 MB; routes answer 413 above this before reading on
_SIGNATURE_PREFIX = "sha256="
# Fake-provider defaults (dev/simulator only; prod requires real values — see core.startup).
DEV_APP_SECRET = "estateos-dev-whatsapp-app-secret"  # noqa: S105 — fake provider only; prod refuses fakes
DEV_VERIFY_TOKEN = "estateos-dev-verify-token"  # noqa: S105 — fake provider only


def sign_body(secret: str, body: bytes) -> str:
    """`X-Hub-Signature-256` value for a body (used by tests and the dev simulator)."""
    return _SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _same(a: str, b: str) -> bool:
    """Constant-time compare that cannot raise on non-ASCII input (headers arrive latin-1 decoded)."""
    return hmac.compare_digest(a.encode("utf-8", "surrogateescape"), b.encode("utf-8", "surrogateescape"))


def verify_signature(body: bytes, header: str | None, secret: str) -> None:
    if not secret:
        raise WebhookRejectedError("app secret not configured")
    if not header or not header.startswith(_SIGNATURE_PREFIX):
        raise WebhookRejectedError("missing or malformed X-Hub-Signature-256")
    if not _same(sign_body(secret, body), header):
        raise WebhookRejectedError("signature mismatch")


def verify_handshake(mode: str | None, token: str | None, challenge: str | None, *, expected_token: str) -> str:
    if not expected_token:
        raise WebhookRejectedError("verify token not configured")
    if mode != "subscribe" or token is None or not _same(token, expected_token):
        raise WebhookRejectedError("webhook verification handshake failed")
    if not challenge or not challenge.isascii() or not challenge.isdigit():
        raise WebhookRejectedError("handshake challenge must be numeric")
    return challenge

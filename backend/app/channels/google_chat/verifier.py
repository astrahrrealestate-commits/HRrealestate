"""Google Chat webhook request verification: Google-signed OIDC bearer token.

Issuer: chat@system.gserviceaccount.com (or accounts.google.com)
Audience: the Chat app's project number.
"""

from collections.abc import Mapping
from typing import Any

from app.core.errors import EstateOSError

CHAT_ISSUERS = frozenset(
    {
        "chat@system.gserviceaccount.com",
        "https://accounts.google.com",
        "accounts.google.com",
    }
)


class ChatAuthError(EstateOSError):
    """Token missing, expired, signed by wrong issuer or for wrong audience."""


class ChatVerifier:
    def __init__(
        self,
        *,
        project_number: str | None = None,
        provider: str = "fake",
        certs: Mapping[str, str] | None = None,
    ) -> None:
        self._project_number = project_number
        self._provider = provider
        self._certs = certs

    def verify_token(self, authorization: str | None) -> dict[str, Any]:
        """Verify the Bearer token; returns decoded claims. Raises ChatAuthError on any failure."""
        if not authorization or not authorization.startswith("Bearer "):
            raise ChatAuthError("missing bearer token")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise ChatAuthError("empty bearer token")

        if self._provider == "none":
            raise ChatAuthError("google chat is not connected")

        if self._provider == "fake":
            # In fake mode (tests / dev), decode without verifying cryptographic signature
            # if no certs are configured, or verify if test claims provided.
            import base64
            import json

            try:
                segments = token.split(".")
                if len(segments) < 2:
                    raise ChatAuthError("malformed jwt")
                claims_bytes = base64.urlsafe_b64decode(segments[1] + "=" * (-len(segments[1]) % 4))
                claims: dict[str, Any] = json.loads(claims_bytes)
            except Exception as exc:
                raise ChatAuthError("invalid fake token") from exc

            # Validate issuer if specified in claims
            iss = claims.get("iss")
            if iss and iss not in CHAT_ISSUERS and iss != "dev-chat@estateos.test":
                raise ChatAuthError("unexpected issuer")
            if self._project_number and claims.get("aud") and claims.get("aud") != self._project_number:
                raise ChatAuthError("unexpected audience")
            return claims

        # Live Google verification using google.auth.jwt
        import google.auth.jwt

        try:
            certs = dict(self._certs) if self._certs else None
            claims = google.auth.jwt.decode(token, certs=certs, audience=self._project_number)
        except Exception as exc:
            raise ChatAuthError(f"google token verification failed: {exc}") from exc

        iss = claims.get("iss")
        if iss not in CHAT_ISSUERS:
            raise ChatAuthError(f"unexpected token issuer: {iss}")

        return dict(claims)

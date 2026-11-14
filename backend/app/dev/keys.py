"""Dev signing keys for fake Pub/Sub OIDC tokens (simulator + tests). The local verifier trusts only these certs."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import google.auth.crypt
import google.auth.jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.channels.gmail.push import DEV_AUDIENCE, DEV_SERVICE_ACCOUNT

__all__ = ["DEV_AUDIENCE", "DEV_SERVICE_ACCOUNT", "KEY_ID", "ensure_dev_keys", "sign_push_token"]

KEY_ID = "estateos-dev-1"


def ensure_dev_keys(directory: Path) -> tuple[str, str]:
    """(private key PEM, cert PEM); created once and reused so api/worker/simulator agree."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path, certs_path = directory / "private.pem", directory / "certs.json"
    if key_path.exists() and certs_path.exists():
        return key_path.read_text(), json.loads(certs_path.read_text())[KEY_ID]
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "estateos-dev")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never world-readable, not even briefly
    with os.fdopen(fd, "w") as fh:
        fh.write(private_pem)
    certs_path.write_text(json.dumps({KEY_ID: cert_pem}))
    return private_pem, cert_pem


def sign_push_token(
    private_pem: str,
    *,
    audience: str = DEV_AUDIENCE,
    email: str = DEV_SERVICE_ACCOUNT,
    issuer: str = "https://accounts.google.com",
    lifetime: int = 3600,
    now: int | None = None,
) -> str:
    issued = int(time.time()) if now is None else now
    payload = {
        "iss": issuer,
        "aud": audience,
        "email": email,
        "email_verified": True,
        "iat": issued,
        "exp": issued + lifetime,
        "sub": "1234567890",
    }
    signer = google.auth.crypt.RSASigner.from_string(private_pem, KEY_ID)
    token: bytes = google.auth.jwt.encode(signer, payload)
    return token.decode()

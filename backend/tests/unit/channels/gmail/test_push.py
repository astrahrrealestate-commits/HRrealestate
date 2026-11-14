import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from app.channels.gmail.push import (
    CLOCK_SKEW_SEC,
    GoogleCerts,
    PushVerifier,
    google_push_verifier,
    local_push_verifier,
    parse_push_body,
)
from app.core.errors import PushRejectedError, WebhookRejectedError
from app.dev.keys import DEV_AUDIENCE, DEV_SERVICE_ACCOUNT, KEY_ID, ensure_dev_keys, sign_push_token


def envelope(email: str = "Hausverwaltung@example.test", history: object = "1234", data: str | None = None) -> bytes:
    payload = data or base64.b64encode(json.dumps({"emailAddress": email, "historyId": history}).encode()).decode()
    message = {"data": payload, "messageId": "pubsub-1", "publishTime": "2026-10-06T08:00:00Z"}
    return json.dumps({"message": message, "subscription": "projects/p/subscriptions/gmail-push"}).encode()


def b64(obj: object) -> str:
    raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


CLAIMS = {
    "iss": "https://accounts.google.com",
    "aud": DEV_AUDIENCE,
    "email": DEV_SERVICE_ACCOUNT,
    "email_verified": True,
}


@pytest.fixture
def keys(tmp_path: Path) -> tuple[str, str, PushVerifier]:
    private, cert = ensure_dev_keys(tmp_path)
    return private, cert, local_push_verifier(tmp_path, DEV_AUDIENCE, DEV_SERVICE_ACCOUNT)


def test_valid_push(keys: tuple[str, str, PushVerifier]) -> None:
    private, _, verifier = keys
    notice = verifier.verify(f"Bearer {sign_push_token(private)}", envelope())
    assert (notice.email, notice.history_id, notice.message_id) == ("hausverwaltung@example.test", 1234, "pubsub-1")


def test_keys_are_reused_and_private_key_is_owner_only(tmp_path: Path) -> None:
    assert ensure_dev_keys(tmp_path) == ensure_dev_keys(tmp_path)
    assert (tmp_path / "private.pem").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "token_kwargs",
    [
        {"audience": "someone-else"},
        {"issuer": "https://evil.example"},
        {"email": "attacker@example.test"},
        {"now": int(time.time()) - 7200, "lifetime": 60},
        {"now": int(time.time()) + 600},
    ],
)
def test_bad_claims_rejected(keys: tuple[str, str, PushVerifier], token_kwargs: dict[str, Any]) -> None:
    private, _, verifier = keys
    with pytest.raises(PushRejectedError):
        verifier.verify(f"Bearer {sign_push_token(private, **token_kwargs)}", envelope())


def test_small_clock_skew_tolerated(keys: tuple[str, str, PushVerifier]) -> None:
    private, _, verifier = keys
    token = sign_push_token(private, now=int(time.time()) + CLOCK_SKEW_SEC - 5)
    assert verifier.verify(f"Bearer {token}", envelope()).history_id == 1234


def test_token_from_other_key_rejected(keys: tuple[str, str, PushVerifier], tmp_path: Path) -> None:
    _, _, verifier = keys
    other_private, _ = ensure_dev_keys(tmp_path / "other")
    with pytest.raises(PushRejectedError):
        verifier.verify(f"Bearer {sign_push_token(other_private)}", envelope())


def test_algorithm_attacks_rejected_not_crashing(keys: tuple[str, str, PushVerifier]) -> None:
    _, cert, verifier = keys
    now = int(time.time())
    claims = {**CLAIMS, "iat": now, "exp": now + 600}
    unsigned = f"{b64({'alg': 'none', 'kid': KEY_ID})}.{b64(claims)}."
    signing_input = f"{b64({'alg': 'HS256', 'kid': KEY_ID})}.{b64(claims)}".encode()
    hs256 = signing_input.decode() + "." + b64(hmac.new(cert.encode(), signing_input, hashlib.sha256).digest())
    ec_input = f"{b64({'alg': 'ES256', 'kid': KEY_ID})}.{b64(claims)}".encode()
    ec_sig = ec.generate_private_key(ec.SECP256R1()).sign(ec_input, ec.ECDSA(hashes.SHA256()))
    es256 = ec_input.decode() + "." + b64(ec_sig)
    no_kid = f"{b64({'alg': 'RS256'})}.{b64(claims)}.sig"
    for token in (unsigned, hs256, es256, no_kid):
        with pytest.raises(PushRejectedError):
            verifier.verify(f"Bearer {token}", envelope())


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ", "Bearer not.a.jwt", "Bearer " + "x" * 9000])
def test_missing_or_garbage_bearer(keys: tuple[str, str, PushVerifier], header: str | None) -> None:
    _, _, verifier = keys
    with pytest.raises(PushRejectedError):
        verifier.verify(header, envelope())


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"[]",
        b"{}",
        b'{"message": {}}',
        envelope(data="!!!"),
        envelope(history="12a"),
        envelope(history="9" * 20),
        envelope(history="9" * 5000),
        envelope(email="nope"),
        b"x" * 70_000,
    ],
)
def test_malformed_envelopes(body: bytes) -> None:
    with pytest.raises(PushRejectedError):
        parse_push_body(body)


def test_rejection_is_a_webhook_rejection() -> None:
    assert issubclass(PushRejectedError, WebhookRejectedError)


def test_local_verifier_picks_up_keys_created_after_startup(tmp_path: Path) -> None:
    verifier = local_push_verifier(tmp_path, DEV_AUDIENCE, DEV_SERVICE_ACCOUNT)
    with pytest.raises(PushRejectedError):
        verifier.verify("Bearer a.b.c", envelope())
    private, _ = ensure_dev_keys(tmp_path)  # simulator creates keys later
    assert verifier.verify(f"Bearer {sign_push_token(private)}", envelope()).history_id == 1234


def test_google_mode_shares_verification_with_cached_certs(tmp_path: Path) -> None:
    private, cert = ensure_dev_keys(tmp_path)
    fetches: list[bool] = []

    def certs(force: bool) -> Mapping[str, str]:
        fetches.append(force)
        return {KEY_ID: cert}

    verifier = google_push_verifier(DEV_AUDIENCE, DEV_SERVICE_ACCOUNT, certs=certs)
    assert verifier.verify(f"Bearer {sign_push_token(private)}", envelope()).history_id == 1234
    assert fetches == [False]


def test_google_certs_cache_honours_max_age() -> None:
    class Response:
        headers: ClassVar[dict[str, str]] = {"Cache-Control": "public, max-age=3600"}

        def raise_for_status(self) -> None: ...

        def json(self) -> dict[str, str]:
            return {"k1": "CERT"}

    class Session:
        calls = 0

        def get(self, url: str, timeout: float) -> Response:
            Session.calls += 1
            return Response()

    cache = GoogleCerts(session=Session())  # type: ignore[arg-type]
    assert cache(False) == {"k1": "CERT"}
    assert cache(False) == {"k1": "CERT"}
    assert Session.calls == 1
    cache(True)
    assert Session.calls == 2

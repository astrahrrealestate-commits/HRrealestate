"""Webhook authentication happens before any database access (engine must never be touched)."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.channels.gmail.push import PushVerifier
from app.channels.whatsapp.webhook_auth import DEV_APP_SECRET, DEV_VERIFY_TOKEN, MAX_WEBHOOK_BYTES, sign_body
from app.core.errors import PushRejectedError
from app.core.settings import Settings
from app.main import create_app

Load = Callable[[str, str], bytes]
SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[call-arg]


class Untouchable:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"database touched before verification: {name}")


class RejectAll(PushVerifier):
    def __init__(self) -> None: ...

    def verify_token(self, authorization: str | None) -> None:
        raise PushRejectedError("nope")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_PROVIDER", "GMAIL_PROVIDER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client() -> TestClient:
    app = create_app(SETTINGS, engine=Untouchable(), workflow_client=MagicMock(), gmail_push_verifier=RejectAll())  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c  # type: ignore[misc]


def test_handshake(client: TestClient) -> None:
    ok = client.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": DEV_VERIFY_TOKEN, "hub.challenge": "42"},
    )
    assert (ok.status_code, ok.text, ok.headers["content-type"].split(";")[0]) == (200, "42", "text/plain")
    bad = client.get(
        "/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "42"}
    )
    assert bad.status_code == 403


@pytest.mark.parametrize("signature", [None, "sha256=" + "0" * 64, "garbage"])
def test_unsigned_or_forged_webhook_rejected_without_db(
    client: TestClient, recorded: Load, signature: str | None
) -> None:
    headers = {"x-hub-signature-256": signature} if signature else {}
    assert client.post("/webhooks/whatsapp", content=recorded("whatsapp", "text"), headers=headers).status_code == 401


def test_oversize_rejected(client: TestClient) -> None:
    body = b" " * (MAX_WEBHOOK_BYTES + 1)
    r = client.post(
        "/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign_body(DEV_APP_SECRET, body)}
    )
    assert r.status_code == 413


def test_signed_but_eventless_body_is_acked_without_db(client: TestClient) -> None:
    body = b'{"object": "whatsapp_business_account", "entry": []}'
    r = client.post(
        "/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign_body(DEV_APP_SECRET, body)}
    )
    assert r.status_code == 200


def test_rejected_push_is_401_without_db(client: TestClient) -> None:
    assert client.post("/webhooks/gmail/push", content=b"{}", headers={"authorization": "Bearer x"}).status_code == 401


def _chunks(size: int) -> Any:
    def gen() -> Any:
        sent = 0
        while sent < size:
            yield b" " * 65536
            sent += 65536

    return gen()


@pytest.mark.parametrize(
    ("path", "size"), [("/webhooks/whatsapp", MAX_WEBHOOK_BYTES + 1), ("/webhooks/gmail/push", 70_000)]
)
def test_chunked_oversize_rejected_before_verification(client: TestClient, path: str, size: int) -> None:
    r = client.post(path, content=_chunks(size), headers={"authorization": "Bearer x"})
    assert r.status_code == 413


def test_default_wiring_builds_lazy_client_and_registry_verifier(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dbos import DBOSClient

    s = Settings(
        database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", dev_signing_dir=tmp_path, _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(s, engine=MagicMock())) as c:
        assert isinstance(c.app.state.workflow_client, DBOSClient)  # type: ignore[attr-defined]
        assert isinstance(c.app.state.gmail_push_verifier, PushVerifier)  # type: ignore[attr-defined]


def test_360dialog_deliveries_are_verified_by_their_own_header(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from app.channels.whatsapp.webhook_auth import DIALOG360

    settings = SETTINGS.model_copy(
        update={
            "whatsapp_provider": "360dialog",
            "whatsapp_app_secret": SecretStr("platform-secret"),
            "whatsapp_api_base_url": "https://waba-v2.360dialog.io",
        }
    )
    app = create_app(settings, engine=Untouchable(), workflow_client=MagicMock(), gmail_push_verifier=RejectAll())  # type: ignore[arg-type]
    body = b'{"object": "whatsapp_business_account", "entry": []}'
    with TestClient(app) as c:
        ok = c.post(
            "/webhooks/whatsapp",
            content=body,
            headers={DIALOG360.header: sign_body("platform-secret", body, DIALOG360)},
        )
        meta_style = c.post(
            "/webhooks/whatsapp", content=body, headers={"x-hub-signature-256": sign_body("platform-secret", body)}
        )
    assert (ok.status_code, meta_style.status_code) == (200, 401)

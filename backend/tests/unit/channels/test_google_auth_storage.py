"""The owner's Google credentials file is private to the owner and the logs never name the account or the path.
The saved scopes are the ones Google granted, not the ones we asked for."""

import asyncio
import stat
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from app.channels.google_auth import (
    REVOKE_URL,
    TOKEN_URL,
    USERINFO_URL,
    disconnect_owner,
    exchange_code_for_tokens,
    save_owner_credentials,
)
from app.core.settings import Settings

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]
CREDS = {"token": "t", "refresh_token": "r", "email": "owner@example.test"}


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _google_revoke() -> Iterator[None]:
    """Disconnect revokes the grant at Google; unit tests never reach the network."""
    with respx.mock(assert_all_called=False) as router:
        router.post(REVOKE_URL).mock(return_value=httpx.Response(200))
        yield


def test_the_credentials_file_is_readable_by_the_owner_only() -> None:
    path = save_owner_credentials(SETTINGS, dict(CREDS))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_saving_and_disconnecting_log_neither_the_email_nor_the_path() -> None:
    with capture_logs() as logs:
        save_owner_credentials(SETTINGS, dict(CREDS))
        disconnect_owner(SETTINGS)
    rendered = repr(logs)
    assert "owner@example.test" not in rendered
    assert "google_owner.json" not in rendered
    assert {entry["event"] for entry in logs} >= {"google_auth.credentials_saved", "google_auth.disconnected"}


def test_a_connect_saves_only_the_scopes_google_granted() -> None:
    granted = "openid https://www.googleapis.com/auth/gmail.modify"
    tokens = {"access_token": "a", "refresh_token": "r", "scope": granted}
    with respx.mock as router:
        router.post(TOKEN_URL).mock(return_value=httpx.Response(200, json=tokens))
        router.get(USERINFO_URL).mock(return_value=httpx.Response(200, json={"email": "owner@example.test"}))
        saved = asyncio.run(exchange_code_for_tokens(SETTINGS, "code"))
    assert saved["scopes"] == granted.split()

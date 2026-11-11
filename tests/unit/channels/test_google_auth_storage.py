"""The owner's Google credentials file is private to the owner and the logs never name the account or the path."""

import stat
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from app.channels.google_auth import disconnect_owner, save_owner_credentials
from app.core.settings import Settings

SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]
CREDS = {"token": "t", "refresh_token": "r", "email": "owner@example.test"}


@pytest.fixture(autouse=True)
def _in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


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

"""Integrations the client does not use are switched off, not faked: Google Chat `none` accepts no webhook token and
builds no outbound client, and Drive filing uses the owner's connected Google account when no Drive file is set."""

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.channels import google_store
from app.channels.google_chat.verifier import ChatAuthError, ChatVerifier
from app.core.settings import Settings
from app.core.startup import production_problems

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def _unsigned_token() -> str:
    """An unsigned JWT claiming Google Chat as issuer: the fake verifier would accept it."""
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return "Bearer " + part({"alg": "none"}) + "." + part({"iss": "chat@system.gserviceaccount.com"}) + "."


def _s(**kw: Any) -> Settings:
    return Settings(_env_file=None, **{"database_url": URL, **kw})


def test_chat_none_rejects_every_token() -> None:
    with pytest.raises(ChatAuthError):
        ChatVerifier(provider="none").verify_token(_unsigned_token())


def test_chat_none_is_not_a_production_problem_but_fake_is() -> None:
    assert not [p for p in production_problems(_s(env="prod", google_chat_provider="none")) if "google_chat" in p]
    assert [p for p in production_problems(_s(env="prod", google_chat_provider="fake")) if "google_chat" in p]


def test_chat_none_builds_no_outbound_client() -> None:

    from app.sender.deps import build_sender_deps

    deps = build_sender_deps(_s(google_chat_provider="none"), MagicMock())
    assert deps.google_chat is None


def test_drive_uses_the_owner_google_account_without_a_drive_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workflows import deps

    monkeypatch.chdir(tmp_path)
    google_store.write_local(json.dumps({"refresh_token": "r", "client_id": "c", "client_secret": "s"}).encode())
    google_store.forget_sync()
    used: list[tuple[Path, object]] = []
    monkeypatch.setattr(
        deps, "build_drive_service", lambda path, scopes=None: used.append((path, scopes)) or MagicMock()
    )
    monkeypatch.setattr(deps, "get_settings", lambda: _s(drive_provider="google"))
    deps._default_drive.cache_clear()
    try:
        deps._default_drive()
    finally:
        deps._default_drive.cache_clear()
    assert used == [(google_store.LOCAL_FILE, None)]  # the login keeps the scopes it was granted

"""Tenant Gmail replies use their own `gmail.send` token; without it send mode blocks Gmail replies."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.channels.gmail.drafts import COMPOSE_SCOPES, SEND_SCOPES, FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.sender.deps import build_sender_deps
from app.sender.gmail import build_gmail_sender, gmail_send_configured
from app.sender.settings import SenderSettings


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[arg-type]


def _sender(**kw: Any) -> SenderSettings:
    return SenderSettings(_env_file=None, **kw)


def test_send_scopes_can_send_and_read_headers_but_are_not_the_compose_scope() -> None:
    assert "https://www.googleapis.com/auth/gmail.send" in SEND_SCOPES
    assert "https://www.googleapis.com/auth/gmail.metadata" in SEND_SCOPES
    assert not set(SEND_SCOPES) & set(COMPOSE_SCOPES)


def test_real_gmail_needs_the_reply_send_token_not_the_drafts_token() -> None:
    drafts_only = _sender(gmail_send_credentials_file=Path("/secrets/gmail-compose.json"))
    assert not gmail_send_configured(_s(gmail_provider="google"), drafts_only)
    with pytest.raises(UnsafeConfigurationError, match="GMAIL_REPLY_SEND_CREDENTIALS_FILE"):
        build_gmail_sender(_s(gmail_provider="google"), drafts_only, "beheer@example.test")
    both = _sender(gmail_reply_send_credentials_file=Path("/secrets/gmail-send.json"))
    assert gmail_send_configured(_s(gmail_provider="google"), both)


def test_fake_gmail_sender_writes_into_the_fake_mailbox() -> None:
    mailbox = FakeMailbox("beheer@example.test", MemoryMailboxStore())
    assert gmail_send_configured(_s(), _sender())
    assert isinstance(build_gmail_sender(_s(), _sender(), "beheer@example.test", fake_mailbox=mailbox), FakeDrafts)
    with pytest.raises(UnsafeConfigurationError):
        build_gmail_sender(_s(), _sender(), "beheer@example.test")


def test_sender_deps_carry_the_cap_and_no_gmail_sender_without_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.sender.deps._sender_settings", lambda: _sender())
    monkeypatch.setattr("app.sender.deps.build_whatsapp_outbound", lambda *_a: MagicMock())
    deps = build_sender_deps(_s(gmail_provider="google", tenant_sends_per_hour=7), MagicMock())
    assert (deps.gmail_sender, deps.tenant_sends_per_hour) == (None, 7)
    assert build_sender_deps(_s(), MagicMock()).gmail_sender is not None

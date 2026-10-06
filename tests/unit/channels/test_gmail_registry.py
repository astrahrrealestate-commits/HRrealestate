from pathlib import Path
from typing import Any

import pytest

from app.channels.gmail.fake import FakeMailbox
from app.channels.gmail.push import PushVerifier
from app.channels.registry import gmail_mailbox, gmail_push_verifier
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.sender.gmail import build_gmail_drafts
from app.sender.settings import SenderSettings


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def test_fake_mailbox_is_shared_on_disk(tmp_path: Path) -> None:
    s = _s(storage_local_dir=tmp_path)
    a, b = gmail_mailbox(s, "Owner@Example.test"), gmail_mailbox(s, "owner@example.test")
    assert isinstance(a, FakeMailbox)
    assert isinstance(b, FakeMailbox)
    a.add_message(b"From: x@example.test\r\n\r\nhi", labels=["INBOX"])
    assert len(b.history_since(0).message_ids) == 1


def test_google_mailbox_needs_credentials() -> None:
    with pytest.raises(UnsafeConfigurationError):
        gmail_mailbox(_s(gmail_provider="google"), "owner@example.test")


def test_push_verifier_selection(tmp_path: Path) -> None:
    assert isinstance(gmail_push_verifier(_s(dev_signing_dir=tmp_path)), PushVerifier)
    google = _s(gmail_provider="google", gmail_pubsub_audience="aud", gmail_pubsub_service_account="sa@p.iam.test")
    assert isinstance(gmail_push_verifier(google), PushVerifier)
    with pytest.raises(UnsafeConfigurationError):
        gmail_push_verifier(_s(gmail_provider="google"))


def test_drafts_factory() -> None:
    with pytest.raises(UnsafeConfigurationError):
        build_gmail_drafts(_s(), SenderSettings(_env_file=None), "o@example.test")  # type: ignore[call-arg]
    with pytest.raises(UnsafeConfigurationError):
        build_gmail_drafts(_s(gmail_provider="google"), SenderSettings(_env_file=None), "o@example.test")  # type: ignore[call-arg]


@pytest.mark.parametrize("address", ["../../etc@x.test", "a@b", "no-at-sign", "a@../x.test", "a..b@x.test"])
def test_mailbox_address_validated_before_becoming_a_path(tmp_path: Path, address: str) -> None:
    with pytest.raises(UnsafeConfigurationError):
        gmail_mailbox(_s(storage_local_dir=tmp_path), address)
    assert not (tmp_path / "fake_gmail").exists() or all(
        p.parent == tmp_path / "fake_gmail" for p in (tmp_path / "fake_gmail").iterdir()
    )

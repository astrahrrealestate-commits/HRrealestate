"""Gmail go-live checks: read-only mailbox access, watch registration, Google push certs, one idempotent draft.

Writes are limited to `users.watch` (idempotent re-registration) and one draft addressed to the mailbox itself.
"""

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.channels import registry
from app.channels.gmail.drafts import DraftRequest
from app.channels.gmail.mime import parse_email
from app.channels.gmail.push import GoogleCerts
from app.core.settings import Settings
from app.sender.gmail import build_gmail_drafts
from app.sender.settings import SenderSettings


def _google(settings: Settings) -> Settings:
    return settings.model_copy(update={"gmail_provider": "google"})


@pytest.mark.live("GMAIL_CREDENTIALS_FILE", "LIVE_GMAIL_MAILBOX")
def test_mailbox_reads_with_readonly_credentials(live_settings: Settings, live_mailbox: str) -> None:
    mailbox = registry.gmail_mailbox(_google(live_settings), live_mailbox)  # verify_address: creds match mailbox
    start = mailbox.current_history_id()
    assert start > 0
    assert mailbox.history_since(start).history_id >= start
    for message_id in mailbox.message_ids_since(datetime.now(UTC) - timedelta(days=2))[:3]:
        assert mailbox.get_message(message_id).raw  # format=raw parses into our model


@pytest.mark.live("GMAIL_CREDENTIALS_FILE", "GMAIL_PUBSUB_TOPIC", "LIVE_GMAIL_MAILBOX")
def test_watch_registers_on_the_pubsub_topic(live_settings: Settings, live_mailbox: str) -> None:
    assert live_settings.gmail_pubsub_topic is not None
    result = registry.gmail_mailbox(_google(live_settings), live_mailbox).watch(live_settings.gmail_pubsub_topic)
    assert result.expiration > datetime.now(UTC) + timedelta(days=1)


@pytest.mark.live("GMAIL_PUBSUB_AUDIENCE", "GMAIL_PUBSUB_SERVICE_ACCOUNT")
def test_google_push_signing_certs_are_reachable() -> None:
    certs = GoogleCerts()(True)
    assert certs
    assert all(pem.startswith("-----BEGIN CERTIFICATE-----") for pem in certs.values())


@pytest.mark.live("GMAIL_CREDENTIALS_FILE", "GMAIL_SEND_CREDENTIALS_FILE", "LIVE_GMAIL_MAILBOX")
def test_draft_is_created_once_as_a_threaded_reply(live_settings: Settings, live_mailbox: str) -> None:
    """Threads exactly like production drafts (Re: subject, In-Reply-To, References), addressed to the mailbox."""
    settings = _google(live_settings)
    mailbox = registry.gmail_mailbox(settings, live_mailbox)
    recent = mailbox.message_ids_since(datetime.now(UTC) - timedelta(days=30))  # newest first
    if not recent:
        pytest.skip("mailbox has no mail in the last 30 days to thread a draft into")
    newest = mailbox.get_message(recent[0])
    parsed = parse_email(newest.raw)
    if not parsed.message_id:
        pytest.skip("newest mail has no Message-ID to reply to")
    references = " ".join(part for part in (parsed.references, parsed.message_id) if part)
    request = DraftRequest(
        idempotency_key="estateos-live-check",
        thread_id=newest.thread_id,
        to=live_mailbox,  # to the mailbox itself: a live check never addresses a tenant
        subject=f"Re: {parsed.subject.removeprefix('Re: ')}",
        body="EstateOS live-check draft. Safe to delete.",
        in_reply_to=parsed.message_id,
        references=references,
    )
    drafts = build_gmail_drafts(settings, SenderSettings(), live_mailbox)
    first = drafts.create_draft(request)
    # Gmail's search index lags a few seconds; a real retry comes seconds later (step backoff), so wait like one.
    deadline = time.monotonic() + 45
    again = drafts.create_draft(request)
    while again != first and time.monotonic() < deadline:
        time.sleep(5)
        again = drafts.create_draft(request)
    assert again == first  # idempotent: the retry finds the existing draft by its Message-ID

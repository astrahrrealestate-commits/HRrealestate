"""Send-mode go-live checks: one real reply through the production `send_reply` path, addressed to the test mailbox
itself (never a tenant), and one WhatsApp text only when the target is the configured owner number.

The Gmail reply threads into the newest mail of the mailbox, sent with the separate reply-send token.
"""

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.channels import registry
from app.channels.gmail.mime import parse_email
from app.channels.whatsapp import payloads
from app.contracts import DraftRequest
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.session import make_engine
from app.sender.deps import build_sender_deps
from app.sender.settings import SenderSettings
from app.sender.whatsapp import build_whatsapp_outbound
from tests.live.requirements import live_requirements
from tests.live.test_live_whatsapp import _owner_of_sending_number, _sending_numbers


@pytest.mark.live(*live_requirements("outbound"))
def test_reply_is_sent_once_to_the_mailbox_itself(live_settings: Settings, live_mailbox: str) -> None:
    settings = live_settings.model_copy(update={"gmail_provider": "google"})
    mailbox = registry.gmail_mailbox(settings, live_mailbox)  # verify_address: read credentials belong to the mailbox
    recent = mailbox.message_ids_since(datetime.now(UTC) - timedelta(days=30))  # newest first
    if not recent:
        pytest.skip("mailbox has no mail in the last 30 days to thread a reply into")
    newest = mailbox.get_message(recent[0])
    parsed = parse_email(newest.raw)
    if not parsed.message_id:
        pytest.skip("newest mail has no Message-ID to reply to")
    request = DraftRequest(
        idempotency_key=f"estateos-live-send-{new_id()}",  # fresh per run: every run really sends
        thread_id=newest.thread_id,
        to=live_mailbox,  # the mailbox itself: a live check never addresses a tenant
        subject=f"Re: {parsed.subject.removeprefix('Re: ')}",
        body="EstateOS outbound live-check. Safe to delete.",
        in_reply_to=parsed.message_id,
        references=" ".join(part for part in (parsed.references, parsed.message_id) if part),
    )
    engine = make_engine(settings.sqlalchemy_url)  # lazy: the send path under test never opens a connection
    try:
        deps = build_sender_deps(settings, engine)
        assert deps.gmail_sender is not None, "GMAIL_REPLY_SEND_CREDENTIALS_FILE did not build a sender"
        sender = deps.gmail_sender(live_mailbox)
        first = sender.send_reply(request)
        assert first
        assert sender.send_reply(request) == first  # retry finds the sent message by X-EstateOS-Key: no second email
    finally:
        engine.dispose()


@pytest.mark.live  # no required settings: opt-in through LIVE_WHATSAPP_TEST_TO, so a Gmail-only check still runs
def test_whatsapp_text_only_to_the_configured_owner(live_settings: Settings) -> None:
    target = os.environ.get("LIVE_WHATSAPP_TEST_TO", "").strip()
    if not target:
        pytest.skip("LIVE_WHATSAPP_TEST_TO is not set")
    sender = SenderSettings()
    if live_settings.whatsapp_provider == "fake" or not sender.whatsapp_access_token:
        pytest.fail("LIVE_WHATSAPP_TEST_TO is set but WhatsApp sending is not configured (provider, access token)")
    if target != os.environ.get("LIVE_WHATSAPP_OWNER", "").strip() or not _owner_of_sending_number(
        live_settings, _sending_numbers(live_settings, sender), target
    ):
        pytest.fail("LIVE_WHATSAPP_TEST_TO is not the configured owner number; refusing to send")
    wamid = build_whatsapp_outbound(live_settings, sender).send(payloads.text(target, "EstateOS outbound live-check"))
    assert wamid.startswith("wamid.")

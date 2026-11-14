"""WhatsApp go-live checks: one text to the owner (Phase 1 sends only to Harjot) and one media download.

The owner must have messaged the business number within 24 hours (free-form text needs an open service window).
The send refuses any number that is not the owner of the company owning the sending number (read from the database
`DATABASE_URL` points to, which must be prod): a typo or a dev seed must never reach anyone else.
"""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import registry
from app.channels.whatsapp import payloads
from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.contracts import Channel
from app.core.settings import Settings
from app.db.models import ChannelAccount, OwnerAccount
from app.db.session import make_engine
from app.sender.settings import SenderSettings
from app.sender.whatsapp import build_whatsapp_outbound


def _sending_numbers(settings: Settings, sender: SenderSettings) -> set[str]:
    """phone_number_ids this deployment sends from: the cloud_api sender id, or the per-number 360dialog keys."""
    if settings.whatsapp_provider == "cloud_api":
        return {sender.whatsapp_phone_number_id} if sender.whatsapp_phone_number_id else set()
    return set(WhatsAppMediaSettings().whatsapp_media_tokens)


def _owner_of_sending_number(settings: Settings, numbers: set[str], e164: str) -> bool:
    """The number must be the owner of the company that owns the sending WhatsApp number (company-scoped)."""
    engine = make_engine(settings.sqlalchemy_url)
    try:
        with Session(engine) as session:
            found = session.scalar(
                select(OwnerAccount.id)
                .join(ChannelAccount, ChannelAccount.company_id == OwnerAccount.company_id)
                .where(
                    ChannelAccount.channel == Channel.whatsapp,
                    ChannelAccount.address.in_(numbers),
                    OwnerAccount.whatsapp_e164 == e164,
                )
            )
        return found is not None
    finally:
        engine.dispose()


@pytest.mark.live(
    "WHATSAPP_PROVIDER", "WHATSAPP_API_BASE_URL", "WHATSAPP_ACCESS_TOKEN", "DATABASE_URL", "LIVE_WHATSAPP_OWNER"
)
def test_text_to_owner_returns_a_wamid(live_settings: Settings) -> None:
    owner, sender = os.environ["LIVE_WHATSAPP_OWNER"], SenderSettings()
    if live_settings.whatsapp_provider == "cloud_api" and not sender.whatsapp_phone_number_id:
        pytest.fail("live-check: missing WHATSAPP_PHONE_NUMBER_ID (required for cloud_api)")
    if not _owner_of_sending_number(live_settings, _sending_numbers(live_settings, sender), owner):
        pytest.fail("LIVE_WHATSAPP_OWNER is not the owner of the sending number's company; refusing to send")
    outbound = build_whatsapp_outbound(live_settings, sender)
    wamid = outbound.send(payloads.text(owner, "EstateOS live-check ✓"))
    assert wamid.startswith("wamid.")


@pytest.mark.live("WHATSAPP_PROVIDER", "WHATSAPP_API_BASE_URL", "WHATSAPP_MEDIA_TOKENS", "LIVE_WHATSAPP_MEDIA")
def test_media_download_with_per_number_token(live_settings: Settings) -> None:
    """LIVE_WHATSAPP_MEDIA = "<phone_number_id>:<media_id>" from a recent inbound image (ids expire after ~30 days)."""
    phone_number_id, media_id = os.environ["LIVE_WHATSAPP_MEDIA"].split(":", 1)
    blob = registry.whatsapp_media(live_settings, phone_number_id).download(media_id)
    assert blob.data
    assert "/" in blob.mime_type

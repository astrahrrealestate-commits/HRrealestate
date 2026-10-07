"""Process-wide sender dependencies built from settings (fakes by default). Only app.sender reads send credentials."""

from functools import lru_cache

from sqlalchemy import Engine

from app.channels import registry
from app.channels.gmail.drafts import GmailDrafts
from app.core.settings import Settings
from app.sender.execute import SenderDeps
from app.sender.gmail import build_gmail_drafts
from app.sender.settings import SenderSettings
from app.sender.whatsapp import build_whatsapp_outbound


@lru_cache(maxsize=1)
def _sender_settings() -> SenderSettings:
    return SenderSettings()


def build_sender_deps(settings: Settings, engine: Engine) -> SenderDeps:
    sender = _sender_settings()

    def drafts(address: str) -> GmailDrafts:
        fake = registry.fake_gmail_mailbox(settings, address) if settings.gmail_provider == "fake" else None
        return build_gmail_drafts(settings, sender, address, fake_mailbox=fake)

    return SenderDeps(engine=engine, whatsapp=build_whatsapp_outbound(settings, sender), gmail_drafts=drafts)

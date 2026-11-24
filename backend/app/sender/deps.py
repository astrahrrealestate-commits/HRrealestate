"""Process-wide sender dependencies built from settings (fakes by default). Only app.sender reads send credentials."""

from functools import lru_cache

from sqlalchemy import Engine

from app.channels import registry
from app.channels.gmail.drafts import GmailDrafts
from app.channels.google_chat.outbound import GoogleChatOutbound
from app.core.settings import Settings
from app.sender.execute import SenderDeps
from app.sender.gmail import build_gmail_drafts, build_gmail_sender, gmail_send_configured
from app.sender.settings import SenderSettings
from app.sender.whatsapp import whatsapp_outbound_or_unconfigured


@lru_cache(maxsize=1)
def _sender_settings() -> SenderSettings:
    return SenderSettings()


def build_sender_deps(settings: Settings, engine: Engine) -> SenderDeps:
    sender = _sender_settings()

    def drafts(address: str) -> GmailDrafts:
        fake = registry.fake_gmail_mailbox(settings, address) if settings.gmail_provider == "fake" else None
        return build_gmail_drafts(settings, sender, address, fake_mailbox=fake)

    def reply_sender(address: str) -> GmailDrafts:
        fake = registry.fake_gmail_mailbox(settings, address) if settings.gmail_provider == "fake" else None
        return build_gmail_sender(settings, sender, address, fake_mailbox=fake)

    google_chat: GoogleChatOutbound | None = None
    if settings.google_chat_provider == "fake":
        from app.channels.google_chat.outbound import FakeGoogleChatOutbound

        google_chat = FakeGoogleChatOutbound()
    elif settings.google_chat_provider == "google":
        from app.channels.google_chat.outbound import GoogleChatClient

        google_chat = GoogleChatClient(sender.google_chat_service_account_file)

    return SenderDeps(
        engine=engine,
        whatsapp=whatsapp_outbound_or_unconfigured(settings, sender),
        gmail_drafts=drafts,
        google_chat=google_chat,
        template_name=settings.owner_template_name,
        template_language=settings.owner_template_language,
        gmail_sender=reply_sender if gmail_send_configured(settings, sender) else None,
        tenant_sends_per_hour=settings.tenant_sends_per_hour,
        owner_chat_sends_per_hour=settings.owner_chat_sends_per_hour,
    )

"""Build inbound-side channel adapters from settings (fakes by default). Outbound adapters are built in app.sender."""

import re
import threading
from functools import lru_cache

from googleapiclient.discovery import build

from app.channels.gmail.fake import DirMailboxStore, FakeMailbox
from app.channels.gmail.google import READ_SCOPES, GoogleMailbox
from app.channels.gmail.ports import GmailMailbox
from app.channels.gmail.push import (
    DEV_AUDIENCE,
    DEV_SERVICE_ACCOUNT,
    PushVerifier,
    google_push_verifier,
    local_push_verifier,
)
from app.channels.whatsapp.fake_media import DirWhatsAppMedia
from app.channels.whatsapp.media import HttpWhatsAppMedia, WhatsAppMedia
from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings


@lru_cache(maxsize=1)
def _media_credentials() -> WhatsAppMediaSettings:
    """Read once per process (not per download)."""
    return WhatsAppMediaSettings()


def whatsapp_media(
    settings: Settings,
    phone_number_id: str,
    *,
    media_settings: WhatsAppMediaSettings | None = None,
) -> WhatsAppMedia:
    """Media adapter for the number that received the message (360dialog keys are per number)."""
    if settings.whatsapp_provider == "fake":
        return fake_whatsapp_media(settings)
    tokens = (media_settings or _media_credentials()).whatsapp_media_tokens
    if not settings.whatsapp_api_base_url or phone_number_id not in tokens:
        raise UnsafeConfigurationError(f"no WhatsApp media credentials for phone_number_id {phone_number_id}")
    token = tokens[phone_number_id].get_secret_value()
    if settings.whatsapp_provider == "360dialog":
        return HttpWhatsAppMedia.dialog360(settings.whatsapp_api_base_url, token)
    return HttpWhatsAppMedia.cloud_api(settings.whatsapp_api_base_url, token)


def fake_whatsapp_media(settings: Settings) -> DirWhatsAppMedia:
    """Shared on-disk fake media (simulator puts, worker downloads)."""
    return DirWhatsAppMedia(settings.storage_local_dir / "fake_whatsapp_media")


def channel_problems(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> list[str]:
    """Channel readiness for real providers (complements core.startup's checks)."""
    if settings.whatsapp_provider == "fake":
        return []
    tokens = (media_settings or _media_credentials()).whatsapp_media_tokens
    return [] if tokens else ["WHATSAPP_MEDIA_TOKENS is empty (needed for inbound media download)"]


def assert_channels_ready(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> None:
    problems = channel_problems(settings, media_settings)
    if problems and settings.env == "prod":
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))


_MAILBOX = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")


def _mailbox_address(address: str) -> str:
    normalised = address.strip().lower()
    if not _MAILBOX.fullmatch(normalised) or ".." in normalised:
        raise UnsafeConfigurationError(f"invalid mailbox address {address[:80]!r}")
    return normalised


def fake_gmail_mailbox(settings: Settings, address: str) -> FakeMailbox:
    """Shared on-disk fake mailbox (simulator writes, api/worker read); the address is validated before it becomes
    a directory name."""
    address = _mailbox_address(address)
    return FakeMailbox(address, DirMailboxStore(settings.storage_local_dir / "fake_gmail" / address))


_local_mailboxes = threading.local()


def gmail_mailbox(settings: Settings, address: str) -> GmailMailbox:
    if settings.gmail_provider == "fake":
        return fake_gmail_mailbox(settings, address)
    if not settings.gmail_credentials_file:
        raise UnsafeConfigurationError("gmail_provider 'google' needs GMAIL_CREDENTIALS_FILE (gmail.readonly)")
    addr = _mailbox_address(address)
    cache: dict[tuple[str, str], GmailMailbox] | None = getattr(_local_mailboxes, "cache", None)
    if cache is None:
        cache = {}
        _local_mailboxes.cache = cache
    key = (str(settings.gmail_credentials_file), addr)
    if key in cache:
        return cache[key]

    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(settings.gmail_credentials_file), READ_SCOPES)
    mailbox = GoogleMailbox(build("gmail", "v1", credentials=creds, cache_discovery=False), addr)
    mailbox.verify_address()  # never read another account's mail under this company
    cache[key] = mailbox
    return mailbox


def gmail_push_verifier(settings: Settings) -> PushVerifier:
    if settings.gmail_provider == "fake":
        audience = settings.gmail_pubsub_audience or DEV_AUDIENCE
        account = settings.gmail_pubsub_service_account or DEV_SERVICE_ACCOUNT
        return local_push_verifier(settings.dev_signing_dir, audience, account)
    if not settings.gmail_pubsub_audience or not settings.gmail_pubsub_service_account:
        raise UnsafeConfigurationError("google push verification needs GMAIL_PUBSUB_AUDIENCE and _SERVICE_ACCOUNT")
    return google_push_verifier(settings.gmail_pubsub_audience, settings.gmail_pubsub_service_account)

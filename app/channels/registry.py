"""Build inbound-side channel adapters from settings (fakes by default). Outbound adapters are built in app.sender."""

from functools import lru_cache

from app.channels.whatsapp.media import FakeWhatsAppMedia, HttpWhatsAppMedia, WhatsAppMedia
from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings


@lru_cache(maxsize=1)
def media_credentials() -> WhatsAppMediaSettings:
    """Read once per process (not per download)."""
    return WhatsAppMediaSettings()


def whatsapp_media(
    settings: Settings,
    phone_number_id: str,
    *,
    media_settings: WhatsAppMediaSettings | None = None,
    fake: FakeWhatsAppMedia | None = None,
) -> WhatsAppMedia:
    """Media adapter for the number that received the message (360dialog keys are per number)."""
    if settings.whatsapp_provider == "fake":
        return fake or FakeWhatsAppMedia()
    tokens = (media_settings or media_credentials()).whatsapp_media_tokens
    if not settings.whatsapp_api_base_url or phone_number_id not in tokens:
        raise UnsafeConfigurationError(f"no WhatsApp media credentials for phone_number_id {phone_number_id}")
    token = tokens[phone_number_id].get_secret_value()
    if settings.whatsapp_provider == "360dialog":
        return HttpWhatsAppMedia.dialog360(settings.whatsapp_api_base_url, token)
    return HttpWhatsAppMedia.cloud_api(settings.whatsapp_api_base_url, token)


def channel_problems(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> list[str]:
    """Channel readiness for real providers (complements core.startup's checks)."""
    if settings.whatsapp_provider == "fake":
        return []
    tokens = (media_settings or media_credentials()).whatsapp_media_tokens
    return [] if tokens else ["WHATSAPP_MEDIA_TOKENS is empty (needed for inbound media download)"]


def assert_channels_ready(settings: Settings, media_settings: WhatsAppMediaSettings | None = None) -> None:
    problems = channel_problems(settings, media_settings)
    if problems and settings.env == "prod":
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))

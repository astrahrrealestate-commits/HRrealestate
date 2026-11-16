"""Outbound WhatsApp adapter construction — the only place that combines send credentials with a transport."""

from typing import Any

from app.channels.whatsapp.outbound import FakeWhatsAppOutbound, HttpWhatsAppOutbound, WhatsAppOutbound
from app.core.errors import UnsafeConfigurationError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.sender.settings import SenderSettings

log = get_logger(__name__)


def build_whatsapp_outbound(settings: Settings, sender: SenderSettings) -> WhatsAppOutbound:
    if settings.whatsapp_provider == "fake":
        return FakeWhatsAppOutbound()
    if not settings.whatsapp_api_base_url or not sender.whatsapp_access_token:
        raise UnsafeConfigurationError("whatsapp outbound needs whatsapp_api_base_url and WHATSAPP_ACCESS_TOKEN")
    token = sender.whatsapp_access_token.get_secret_value()
    if settings.whatsapp_provider == "360dialog":
        return HttpWhatsAppOutbound.dialog360(settings.whatsapp_api_base_url, token)
    if not sender.whatsapp_phone_number_id:
        raise UnsafeConfigurationError("cloud_api outbound needs WHATSAPP_PHONE_NUMBER_ID")
    return HttpWhatsAppOutbound.cloud_api(settings.whatsapp_api_base_url, sender.whatsapp_phone_number_id, token)


class UnconfiguredWhatsAppOutbound:
    """Stands in for WhatsApp outbound that is not configured, outside ENV=prod only (prod refuses to boot instead).
    Building the sender for a dashboard-only delivery (briefing, alert) must not fail on WhatsApp; a WhatsApp send
    still does, with the reason the real adapter could not be built."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def send(self, payload: dict[str, Any]) -> str:
        raise UnsafeConfigurationError(self._reason)


def whatsapp_outbound_or_unconfigured(settings: Settings, sender: SenderSettings) -> WhatsAppOutbound:
    try:
        return build_whatsapp_outbound(settings, sender)
    except UnsafeConfigurationError as exc:
        if settings.env == "prod":
            raise
        log.warning("sender.whatsapp_unconfigured", reason=str(exc))
        return UnconfiguredWhatsAppOutbound(str(exc))

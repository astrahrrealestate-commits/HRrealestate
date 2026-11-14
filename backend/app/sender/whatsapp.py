"""Outbound WhatsApp adapter construction — the only place that combines send credentials with a transport."""

from app.channels.whatsapp.outbound import FakeWhatsAppOutbound, HttpWhatsAppOutbound, WhatsAppOutbound
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.sender.settings import SenderSettings


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

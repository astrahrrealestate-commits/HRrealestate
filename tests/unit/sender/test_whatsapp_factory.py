from typing import Any

import pytest

from app.channels.whatsapp.outbound import FakeWhatsAppOutbound, HttpWhatsAppOutbound
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.sender.settings import SenderSettings
from app.sender.whatsapp import build_whatsapp_outbound


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def _sender(**kw: Any) -> SenderSettings:
    return SenderSettings(_env_file=None, **kw)  # type: ignore[call-arg]


def test_fake_by_default() -> None:
    assert isinstance(build_whatsapp_outbound(_s(), _sender()), FakeWhatsAppOutbound)


@pytest.mark.parametrize(
    ("provider", "url", "header", "value"),
    [
        ("cloud_api", "https://example.invalid/1/messages", "Authorization", "Bearer t"),
        ("360dialog", "https://example.invalid/messages", "D360-API-KEY", "t"),
    ],
)
def test_real_providers(provider: str, url: str, header: str, value: str) -> None:
    s = _s(whatsapp_provider=provider, whatsapp_api_base_url="https://example.invalid")
    adapter = build_whatsapp_outbound(s, _sender(whatsapp_access_token="t", whatsapp_phone_number_id="1"))
    assert isinstance(adapter, HttpWhatsAppOutbound)
    assert adapter._url == url
    assert adapter._headers[header] == value


@pytest.mark.parametrize(
    ("provider", "sender_kw"),
    [("cloud_api", {}), ("cloud_api", {"whatsapp_access_token": "t"}), ("360dialog", {})],
)
def test_missing_credentials_fail_loudly(provider: str, sender_kw: dict[str, Any]) -> None:
    s = _s(whatsapp_provider=provider, whatsapp_api_base_url="https://example.invalid")
    with pytest.raises(UnsafeConfigurationError):
        build_whatsapp_outbound(s, _sender(**sender_kw))

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
        ("sendzen", "https://example.invalid/v1/messages", "Authorization", "Bearer t"),
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
    [("cloud_api", {}), ("cloud_api", {"whatsapp_access_token": "t"}), ("360dialog", {}), ("sendzen", {})],
)
def test_missing_credentials_fail_loudly(provider: str, sender_kw: dict[str, Any]) -> None:
    s = _s(whatsapp_provider=provider, whatsapp_api_base_url="https://example.invalid")
    with pytest.raises(UnsafeConfigurationError):
        build_whatsapp_outbound(s, _sender(**sender_kw))


def test_sendzen_template_payload_and_message_id() -> None:
    import json

    import httpx
    import respx

    from app.channels.whatsapp.payloads import template

    with respx.mock(assert_all_called=True) as router:

        def check_request(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body.get("template_name") == "estateos_pending"
            assert body.get("components") == [{"type": "body", "parameters": [{"type": "text", "text": "5"}]}]
            assert request.headers.get("Authorization") == "Bearer my-token"
            return httpx.Response(200, json={"message_id": "sz_msg_12345", "status": "sent", "to": "31600000000"})

        router.post("https://api.sendzen.io/v1/messages").mock(side_effect=check_request)
        outbound = HttpWhatsAppOutbound.sendzen("https://api.sendzen.io/v1", "my-token")
        wamid = outbound.send(template("+31600000000", "estateos_pending", "en", ["5"]))
        assert wamid == "sz_msg_12345"


def test_unconfigured_outbound_outside_prod_fails_at_send_not_at_build() -> None:
    """AWS runs ENV=dev with WhatsApp not configured yet: the daily briefing builds the sender to post to the
    dashboard and must not crash on WhatsApp; a real WhatsApp send still fails loudly."""
    from app.sender.whatsapp import whatsapp_outbound_or_unconfigured

    s = _s(whatsapp_provider="cloud_api", env="dev")
    adapter = whatsapp_outbound_or_unconfigured(s, _sender())
    with pytest.raises(UnsafeConfigurationError):
        adapter.send({"messaging_product": "whatsapp", "to": "31600000000", "type": "text"})


def test_unconfigured_outbound_in_prod_still_fails_at_build() -> None:
    from app.sender.whatsapp import whatsapp_outbound_or_unconfigured

    with pytest.raises(UnsafeConfigurationError):
        whatsapp_outbound_or_unconfigured(_s(whatsapp_provider="cloud_api", env="prod"), _sender())

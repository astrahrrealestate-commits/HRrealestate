from typing import Any

import pytest

from app.channels.registry import assert_channels_ready, channel_problems, whatsapp_media
from app.channels.whatsapp.fake_media import DirWhatsAppMedia
from app.channels.whatsapp.media import HttpWhatsAppMedia
from app.channels.whatsapp.media_settings import WhatsAppMediaSettings
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings

BASE = "https://waba-v2.360dialog.io"


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def _media(**tokens: str) -> WhatsAppMediaSettings:
    return WhatsAppMediaSettings(whatsapp_media_tokens=tokens, _env_file=None)  # type: ignore[call-arg, arg-type]


def test_fake_media_by_default() -> None:
    assert isinstance(whatsapp_media(_s(), "100000000000001"), DirWhatsAppMedia)


@pytest.mark.parametrize(("provider", "header"), [("cloud_api", "Authorization"), ("360dialog", "D360-API-KEY")])
def test_real_media_uses_the_receiving_numbers_token(provider: str, header: str) -> None:
    s = _s(whatsapp_provider=provider, whatsapp_api_base_url=BASE)
    adapter = whatsapp_media(s, "222", media_settings=_media(**{"111": "tenant-key", "222": "agent-key"}))
    assert isinstance(adapter, HttpWhatsAppMedia)
    assert "agent-key" in adapter._headers[header]


def test_unknown_number_has_no_credentials() -> None:
    s = _s(whatsapp_provider="360dialog", whatsapp_api_base_url=BASE)
    with pytest.raises(UnsafeConfigurationError, match="333"):
        whatsapp_media(s, "333", media_settings=_media(**{"111": "k"}))


def test_channel_readiness() -> None:
    assert channel_problems(_s()) == []
    real = _s(whatsapp_provider="360dialog", whatsapp_api_base_url=BASE)
    assert channel_problems(real, _media()) != []
    assert channel_problems(real, _media(**{"1": "k"})) == []
    assert_channels_ready(real, _media())  # dev: reported, not fatal
    prod = real.model_copy(update={"env": "prod"})
    with pytest.raises(UnsafeConfigurationError):
        assert_channels_ready(prod, _media())

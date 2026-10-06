"""Credentials for inbound WhatsApp media download. Imported ONLY by app.channels.registry (import-linter).

Residual risk (ADR 0003 amendment): provider media credentials can also send messages (a 360dialog API key is per
number and can POST /messages; Meta media download needs the messaging scope). They are therefore kept out of the
global Settings, keyed per phone number, and unreachable from any module except the registry.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class WhatsAppMediaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # JSON object in env: WHATSAPP_MEDIA_TOKENS={"<phone_number_id>": "<token or D360 API key>", ...}
    whatsapp_media_tokens: dict[str, SecretStr] = {}

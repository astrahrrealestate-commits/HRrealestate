"""Send credentials. Imported only within app.sender (import-linter contract + edit guard)."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SenderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    gmail_send_credentials_file: Path | None = None

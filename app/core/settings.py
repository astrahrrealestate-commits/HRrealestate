"""Runtime configuration from environment / .env. Send credentials live in app.sender.settings, not here."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

import app


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_parse_none_str="",  # `NAME=` means unset
    )

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: PostgresDsn
    api_port: int = 8000
    app_version: str = app.__version__

    sentry_dsn: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    # LLM agents (spec phase-1 agents). `fake` = deterministic offline models (app.llm.fakes); prod refuses it.
    llm_model: str = "fake"  # Pydantic AI model string, e.g. "openai:gpt-4.1-mini"
    llm_timeout_sec: float = 60.0

    # Owner channel: approved WhatsApp template that reopens the 24-hour window ("{{1}} items need you").
    owner_template_name: str = "estateos_pending"
    owner_template_language: str = "en"

    # Channels (spec M2 §4). Defaults are fakes: everything runs without provider access; prod refuses fakes.
    whatsapp_provider: Literal["fake", "cloud_api", "360dialog"] = "fake"
    gmail_provider: Literal["fake", "google"] = "fake"
    whatsapp_app_secret: SecretStr | None = None  # webhook HMAC: Meta app secret or 360dialog platform secret
    whatsapp_verify_token: SecretStr | None = None  # webhook subscription handshake
    whatsapp_api_base_url: str | None = None  # e.g. https://graph.facebook.com/v21.0 or https://waba-v2.360dialog.io
    gmail_pubsub_audience: str | None = None  # OIDC audience configured on the Pub/Sub push subscription
    gmail_pubsub_service_account: str | None = None  # expected `email` claim of the push token
    gmail_pubsub_topic: str | None = None  # projects/<p>/topics/<t> used by users.watch
    gmail_credentials_file: Path | None = None  # authorized-user JSON (Workspace internal OAuth app)

    storage_backend: Literal["local", "memory", "s3"] = "local"
    storage_local_dir: Path = Path(".data/storage")
    dev_signing_dir: Path = Path(".data/dev-keys")  # simulator keys for fake Pub/Sub tokens

    s3_region: str = "eu-central-1"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    @property
    def sqlalchemy_url(self) -> str:
        return str(self.database_url)

    @property
    def dbos_database_url(self) -> str:
        """DBOS wants a plain `postgresql://` URL; SQLAlchemy uses the `+psycopg` driver suffix."""
        scheme, rest = self.sqlalchemy_url.split("://", 1)
        return f"{scheme.split('+', 1)[0]}://{rest}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # database_url comes from the environment

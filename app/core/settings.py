"""Runtime configuration from environment / .env. Send credentials live in app.sender.settings, not here."""

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

import app


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: PostgresDsn
    api_port: int = 8000
    app_version: str = app.__version__
    pipeline_concurrency: int = 4

    sentry_dsn: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

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

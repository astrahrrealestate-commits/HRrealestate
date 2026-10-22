"""Runtime configuration from environment / .env. Send credentials live in app.sender.settings, not here."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

import app

EMBEDDING_DIMENSIONS = 1024  # text-embedding-3-small at 1024 dimensions; the `vector` column size (ADR 0008)


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
    gemini_api_key: SecretStr | None = None  # Google AI Studio key for `google-gla:*` models (testing)

    # LLM agents (spec phase-1 agents). `fake` = deterministic offline models (app.llm.fakes); prod refuses it.
    llm_model: str = "fake"  # Pydantic AI model string, e.g. "openai:gpt-4.1-mini" or "google-gla:gemini-2.5-flash"
    llm_timeout_sec: float = 60.0
    # Advanced retrieval (ADR 0008). `fake` = deterministic hashing embedder (tests, simulator); prod refuses it.
    embedding_model: str = "fake"  # e.g. "openai:text-embedding-3-small" or "google-gla:gemini-embedding-001"
    rag_query_rewrite: bool = True  # one small LLM call per question: keyword variants, HyDE passage, fact label
    rag_rerank: bool = True  # listwise LLM rerank of the fused candidates
    llm_max_output_tokens: int = 4000  # structural cap per call, always on
    # Usage limits: None = unlimited (shipped disabled; set the env var to enable). Per company, UTC day/month.
    llm_daily_budget_usd: Decimal | None = None
    llm_monthly_budget_usd: Decimal | None = None
    llm_daily_calls_cap: int | None = None
    owner_qa_daily_cap: int | None = None  # owner questions per day
    owner_qa_daily_budget_usd: Decimal | None = None
    concierge_daily_cap: int | None = None  # Super Agent plans per day
    concierge_daily_budget_usd: Decimal | None = None

    # Owner channel: approved WhatsApp template that reopens the 24-hour window ("{{1}} items need you").
    owner_template_name: str = "estateos_pending"
    owner_template_language: str = "en"
    # Send mode (companies.outbound_mode=send): tenant replies per company per rolling hour; at the cap → blocked.
    tenant_sends_per_hour: int = 30

    # Channels (spec M2 §4). Defaults are fakes: everything runs without provider access; prod refuses fakes.
    whatsapp_provider: Literal["fake", "cloud_api", "360dialog"] = "fake"
    gmail_provider: Literal["fake", "google"] = "fake"
    google_chat_provider: Literal["fake", "google"] = "fake"
    google_chat_project_number: str | None = None
    whatsapp_app_secret: SecretStr | None = None  # webhook HMAC: Meta app secret or 360dialog platform secret
    whatsapp_verify_token: SecretStr | None = None  # webhook subscription handshake
    whatsapp_api_base_url: str | None = None  # e.g. https://graph.facebook.com/v21.0 or https://waba-v2.360dialog.io
    gmail_pubsub_audience: str | None = None  # OIDC audience configured on the Pub/Sub push subscription
    gmail_pubsub_service_account: str | None = None  # expected `email` claim of the push token
    gmail_pubsub_topic: str | None = None  # projects/<p>/topics/<t> used by users.watch
    gmail_credentials_file: Path | None = None  # authorized-user JSON (Workspace internal OAuth app)

    # Document filing (#9, ADR 0005): Drive with the `drive.file` scope only.
    drive_provider: Literal["fake", "google"] = "fake"
    drive_credentials_file: Path | None = None  # authorized-user JSON created with the drive.file scope
    doc_read_content: bool = True  # M10, ADR 0007: read attachment text to file, link and answer; off = metadata only

    # Dashboard (owner interface, ADR 0006). `fake` accepts test tokens; prod refuses it.
    dashboard_auth_provider: Literal["fake", "google"] = "fake"
    dashboard_session_secret: SecretStr | None = None
    dashboard_session_ttl_min: int = 480
    dashboard_trust_forwarded_for: bool = False  # rate-limit login by X-Forwarded-For (only behind a trusted proxy)
    google_oauth_client_id: str | None = None  # audience of the owner's Google ID token
    # Exact SPA origins allowed cross-origin (comma-separated). Empty = no CORS (the SPA is served same-origin).
    dashboard_cors_origins: Annotated[list[str], NoDecode] = []

    storage_backend: Literal["local", "memory", "s3"] = "local"
    storage_local_dir: Path = Path(".data/storage")
    dev_signing_dir: Path = Path(".data/dev-keys")  # simulator keys for fake Pub/Sub tokens

    s3_region: str = "eu-central-1"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    @field_validator("dashboard_cors_origins", mode="before")
    @classmethod
    def _cors_origins(cls, value: object) -> object:
        """`https://a.example,https://b.example` or a list; a wildcard is refused (cookies ride along)."""
        if value is None:  # `DASHBOARD_CORS_ORIGINS=` (empty means unset)
            return []
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list):
            return value
        origins = [str(item).strip().rstrip("/") for item in items if str(item).strip()]
        if any("*" in origin for origin in origins):
            raise ValueError("DASHBOARD_CORS_ORIGINS must list exact origins, never '*'")
        return origins

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

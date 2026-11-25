"""Runtime configuration from environment / .env. Send credentials live in app.sender.settings, not here."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import PositiveInt, PostgresDsn, SecretStr, field_validator
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
    groq_api_key: SecretStr | None = None  # Groq Cloud key (https://console.groq.com) for `groq:*` models

    # LLM agents (spec phase-1 agents). `fake` = deterministic offline models (app.llm.fakes); prod refuses it.
    llm_model: str = "fake"  # Pydantic AI model string, e.g. "openai:gpt-4.1-mini" or "google-gla:gemini-2.5-flash"
    # Model for the Super Agent's concierge planner when it should differ from `llm_model` (e.g. a cheap Gemini Flash
    # for intent routing); empty = use `llm_model`.
    concierge_model: str = ""
    # Astra's research must answer within this. The browser gives up at 55 s (`askAgent`), the load balancer at its idle
    # timeout: raise all three together (90 s here needs 120 s there).
    super_agent_deadline_sec: float = 35.0
    llm_timeout_sec: float = 60.0
    # Tried in order when `llm_model` answers an error (Pydantic AI FallbackModel), e.g. "openai:gpt-4.1-mini". A
    # fallback whose provider key is not set is left out, so naming one is harmless until its key exists.
    llm_fallback_models: Annotated[list[str], NoDecode] = []
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
    concierge_worker_concurrency: PositiveInt = 4  # Super Agent turns running at once per worker (chat queue)

    # Owner channel: approved WhatsApp template that reopens the 24-hour window ("{{1}} items need you").
    owner_template_name: str = "estateos_pending"
    owner_template_language: str = "en"
    owner_email: str | None = ""
    owner_phone: str | None = ""
    # Send mode (companies.outbound_mode=send): tenant replies per company per rolling hour; at the cap → blocked.
    tenant_sends_per_hour: int = 30
    # Owner-typed WhatsApp sends from the Chats page (ADR 0013): a separate per-company hourly cap.
    owner_chat_sends_per_hour: int = 200
    owner_chat_sends_per_number_per_hour: int = 20  # to one contact: a typing slip or a loop cannot flood a tenant

    # Channels (spec M2 §4). Defaults are fakes: everything runs without provider access; prod refuses fakes.
    whatsapp_provider: Literal["fake", "cloud_api", "360dialog", "sendzen"] = "fake"
    gmail_provider: Literal["fake", "google"] = "fake"
    google_chat_provider: Literal["none", "fake", "google"] = "fake"  # none = not used: every webhook refused
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

    calendar_provider: Literal["fake", "google"] = "fake"
    calendar_credentials_file: Path | None = None

    # Quote checker (M11, spec 2026-10-31). Percent thresholds are over the reference price; `fake` = deterministic
    # offline prices (tests, simulator); prod refuses it.
    price_source: Literal["fake", "competitors", "web"] = "fake"
    # Web prices (ADR 0009): which search API feeds `price_source=web`. `none` = not connected yet; `fake` = recorded
    # pages (tests, simulator). A real provider adds one SearchClient implementation and one literal here.
    price_search_provider: Literal["none", "fake"] = "none"
    price_allowed_domains: Annotated[list[str], NoDecode] = []  # hosts web prices may come from; empty = any
    finance_ok_pct: Decimal = Decimal(5)  # up to this much over the reference is still ok
    finance_above_market_pct: Decimal = Decimal(15)  # over this: above market
    finance_well_above_pct: Decimal = Decimal(30)  # over this: well above market
    finance_low_ratio: Decimal = Decimal("0.5")  # a line under this share of the reference is suspiciously low
    finance_late_days: int = 7  # a quote this many days after the work counts as late
    finance_min_samples: int = 3  # fewer market samples than this is not a reference
    finance_vat_rate: Decimal = Decimal("0.21")  # Dutch standard VAT, used to normalise incl/excl quotes
    finance_daily_lookup_cap: int = 40  # market price lookups per company per day

    # Due diligence lite (spec 2026-10-31). A JSON file in the `Framework` shape replaces the default checklist.
    dd_framework_path: Path | None = None
    dd_max_documents: int = 30  # documents per review

    # Dashboard (owner interface, ADR 0006). `fake` accepts test tokens; prod refuses it.
    dashboard_auth_provider: Literal["fake", "google"] = "fake"
    dashboard_session_secret: SecretStr | None = None
    dashboard_session_ttl_min: int = 480
    dashboard_trust_forwarded_for: bool = False  # rate-limit login by X-Forwarded-For (only behind a trusted proxy)
    google_oauth_client_id: str | None = None  # audience of the owner's Google ID token
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str | None = "http://localhost:8000/api/auth/google/callback"
    # Where the API sends the browser after a Google flow (the SPA origin) and the callback of the owner login. Prod
    # refuses the localhost defaults (core/startup.py).
    frontend_base_url: str = "http://localhost:3000"
    # Cookie Domain when the SPA and the API sit on sibling hosts (api.x.com and app.x.com): the SPA middleware must see
    # the session cookie the API sets. None keeps it host-only, which is right for one host or for localhost.
    dashboard_cookie_domain: str | None = None
    google_login_redirect_uri: str = "http://localhost:8000/api/auth/login/google/callback"
    # Exact SPA origins allowed cross-origin (comma-separated). Empty = no CORS (the SPA is served same-origin).
    dashboard_cors_origins: Annotated[list[str], NoDecode] = []

    # BRIXX data mirror (read-only). `fake` = in-process fixtures; prod refuses it. The token is a per-user secret.
    brixx_provider: Literal["fake", "api"] = "fake"
    brixx_base_url: str = "https://mob.brixxonline.com/api/v1"
    brixx_environment: str = "hrrealestate"
    brixx_token: SecretStr | None = None
    brixx_auth_scheme: Literal["raw", "bearer"] = "bearer"  # Authorization header: the bare token or `Bearer <token>`
    brixx_sync_interval_minutes: PositiveInt = 15
    brixx_timeout_sec: float = 60.0

    storage_backend: Literal["local", "memory", "s3"] = "local"
    storage_local_dir: Path = Path(".data/storage")
    dev_signing_dir: Path = Path(".data/dev-keys")  # simulator keys for fake Pub/Sub tokens
    translation_model_dir: Path = Path(".data/models/opus-mt-nl-en")  # `make translation-model`; baked into the image
    translation_model_dir_en_nl: Path = Path(".data/models/opus-mt-en-nl")

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

    @field_validator("llm_fallback_models", mode="before")
    @classmethod
    def _fallback_models(cls, value: object) -> object:
        """`openai:gpt-4.1-mini,groq:llama-3.3-70b-versatile` or a list; blanks dropped."""
        if value is None:
            return []
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list):
            return value
        return [str(item).strip() for item in items if str(item).strip()]

    @field_validator("price_allowed_domains", mode="before")
    @classmethod
    def _price_domains(cls, value: object) -> object:
        """`a.example,b.example` or a list; lower-cased bare hosts, so a wildcard or a URL is refused."""
        if value is None:  # `PRICE_ALLOWED_DOMAINS=` (empty means unset)
            return []
        items = value.split(",") if isinstance(value, str) else value
        if not isinstance(items, list):
            return value
        domains = [str(item).strip().lower().rstrip("/") for item in items if str(item).strip()]
        if any("*" in d or "://" in d for d in domains):
            raise ValueError("PRICE_ALLOWED_DOMAINS must list bare hosts such as shop.example, no wildcard or scheme")
        return domains

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

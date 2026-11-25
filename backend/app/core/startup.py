"""Fail-fast configuration checks run by every process (API factory, worker) before serving."""

from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings

GEMINI = "google-gla:"


def _model_problems(settings: Settings) -> list[str]:
    """Prod runs the Gemini API only (M13): every model, fallback and embedding is a `google-gla:` model on the one key;
    `fake` and any other provider are refused. Empty overrides (concierge, quality) fall back to `llm_model`."""
    named = [("llm_model", settings.llm_model), ("embedding_model", settings.embedding_model)]
    named += [(f, v) for f, v in (("concierge_model", settings.concierge_model),
                                  ("llm_quality_model", settings.llm_quality_model)) if v]  # fmt: skip
    named += [("llm_fallback_models", m) for m in settings.llm_fallback_models]
    problems = [
        f"{field} is {value!r}" if value in ("fake", "test") else f"{field} is {value!r}: prod runs Gemini only"
        for field, value in named
        if value in ("fake", "test") or not value.startswith(GEMINI)
    ]
    if not settings.gemini_api_key:
        problems.append("gemini_api_key is not set (prod runs Gemini only)")
    return problems


def production_problems(settings: Settings) -> list[str]:
    if settings.env != "prod":
        return []
    problems: list[str] = []
    if settings.whatsapp_provider == "fake":
        problems.append("whatsapp_provider is 'fake'")
    if settings.gmail_provider == "fake":
        problems.append("gmail_provider is 'fake'")
    if settings.brixx_provider == "fake":
        problems.append("brixx_provider is 'fake'")
    elif not settings.brixx_token:
        problems.append("brixx_token is not set")
    problems += _model_problems(settings)
    if settings.drive_provider == "fake":
        problems.append("drive_provider is 'fake'")
    if settings.google_chat_provider == "fake":
        problems.append("google_chat_provider is 'fake' (it accepts unsigned tokens)")
    elif settings.google_chat_provider == "google" and not settings.google_chat_project_number:
        problems.append("google_chat_project_number is not set (the Chat token audience)")
    drive = settings.drive_credentials_file
    if drive is None or not drive.is_file():
        problems.append("drive_credentials_file is not set or not a readable file")
    if settings.storage_backend != "s3":
        problems.append(f"storage_backend is {settings.storage_backend!r} (prod needs 's3')")
    for name in (
        "whatsapp_app_secret",
        "whatsapp_verify_token",
        "whatsapp_api_base_url",
        "gmail_pubsub_audience",
        "gmail_pubsub_service_account",
        "gmail_pubsub_topic",
        "s3_bucket",
    ):
        if not getattr(settings, name):
            problems.append(f"{name} is not set")
    if settings.price_source == "fake":
        problems.append("price_source is 'fake'")
    if settings.price_source == "web" and settings.price_search_provider in ("none", "fake"):
        provider = settings.price_search_provider
        problems.append(f"price_search_provider is {provider!r} (price_source 'web' needs a real search provider)")
    if settings.dashboard_auth_provider == "fake":
        problems.append("dashboard_auth_provider is 'fake'")
    secret = settings.dashboard_session_secret
    if secret is None or len(secret.get_secret_value()) < 32:
        problems.append("dashboard_session_secret is not set or shorter than 32 characters")
    if secret is not None and secret.get_secret_value().lower().startswith("dev-only"):
        problems.append("dashboard_session_secret is the public dev-only default (backend/docker/compose.yml)")
    if not settings.google_oauth_client_id:
        problems.append("google_oauth_client_id is not set")
    for name in ("frontend_base_url", "google_login_redirect_uri", "google_oauth_redirect_uri"):
        value = getattr(settings, name) or ""
        if not value.startswith("https://") or "localhost" in value or "127.0.0.1" in value:
            problems.append(f"{name} must be a public https URL (it is {value!r})")
    creds = settings.gmail_credentials_file
    if creds is None or not creds.is_file():
        problems.append("gmail_credentials_file is not set or not a readable file")
    return problems


def assert_production_safe(settings: Settings) -> None:
    problems = production_problems(settings)
    if problems:
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))

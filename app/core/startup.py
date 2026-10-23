"""Fail-fast configuration checks run by every process (API factory, worker) before serving."""

from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings


def production_problems(settings: Settings) -> list[str]:
    if settings.env != "prod":
        return []
    problems: list[str] = []
    if settings.whatsapp_provider == "fake":
        problems.append("whatsapp_provider is 'fake'")
    if settings.gmail_provider == "fake":
        problems.append("gmail_provider is 'fake'")
    if settings.llm_model in ("fake", "test"):
        problems.append(f"llm_model is {settings.llm_model!r}")
    elif settings.llm_model.startswith("openai:") and not settings.openai_api_key:
        problems.append("openai_api_key is not set (llm_model is an openai model)")
    elif settings.llm_model.startswith("google-gla:") and not settings.gemini_api_key:
        problems.append("gemini_api_key is not set (llm_model is a gemini model)")
    elif settings.llm_model.startswith("groq:") and not settings.groq_api_key:
        problems.append("groq_api_key is not set (llm_model is a groq model)")
    if settings.drive_provider == "fake":
        problems.append("drive_provider is 'fake'")
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
    if settings.dashboard_auth_provider == "fake":
        problems.append("dashboard_auth_provider is 'fake'")
    secret = settings.dashboard_session_secret
    if secret is None or len(secret.get_secret_value()) < 32:
        problems.append("dashboard_session_secret is not set or shorter than 32 characters")
    if secret is not None and secret.get_secret_value().lower().startswith("dev-only"):
        problems.append("dashboard_session_secret is the public dev-only default (docker/compose.yml)")
    if not settings.google_oauth_client_id:
        problems.append("google_oauth_client_id is not set")
    creds = settings.gmail_credentials_file
    if creds is None or not creds.is_file():
        problems.append("gmail_credentials_file is not set or not a readable file")
    return problems


def assert_production_safe(settings: Settings) -> None:
    problems = production_problems(settings)
    if problems:
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))

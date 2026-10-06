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
    if settings.storage_backend != "s3":
        problems.append(f"storage_backend is {settings.storage_backend!r} (prod needs 's3')")
    for name in (
        "whatsapp_app_secret",
        "whatsapp_verify_token",
        "whatsapp_api_base_url",
        "gmail_pubsub_audience",
        "gmail_pubsub_service_account",
        "gmail_credentials_file",
        "gmail_pubsub_topic",
    ):
        if not getattr(settings, name):
            problems.append(f"{name} is not set")
    return problems


def assert_production_safe(settings: Settings) -> None:
    problems = production_problems(settings)
    if problems:
        raise UnsafeConfigurationError("refusing to start in prod: " + "; ".join(problems))

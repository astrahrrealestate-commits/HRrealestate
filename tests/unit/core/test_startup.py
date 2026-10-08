from pathlib import Path
from typing import Any

import pytest

from app.core.settings import Settings
from app.core.startup import UnsafeConfigurationError, assert_production_safe

URL = "postgresql+psycopg://u:p@localhost:5433/db"
REAL: dict[str, Any] = {
    "whatsapp_provider": "cloud_api",
    "gmail_provider": "google",
    "storage_backend": "s3",
    "whatsapp_app_secret": "s",
    "whatsapp_verify_token": "t",
    "gmail_pubsub_audience": "https://estateos.example/webhooks/gmail/push",
    "whatsapp_api_base_url": "https://waba-v2.360dialog.io",
    "gmail_pubsub_service_account": "push@p.iam.gserviceaccount.com",
    "gmail_pubsub_topic": "projects/p/topics/gmail",
    "s3_bucket": "estateos-prod",
    "llm_model": "openai:gpt-4.1-mini",
    "openai_api_key": "sk-test",
    "drive_provider": "google",
}


@pytest.fixture(autouse=True)
def _credentials_file(tmp_path: Path) -> None:
    creds = tmp_path / "gmail-read.json"
    creds.write_text("{}")
    REAL["gmail_credentials_file"] = creds
    drive = tmp_path / "drive-file.json"
    drive.write_text("{}")
    REAL["drive_credentials_file"] = drive


def _s(**kw: Any) -> Settings:
    return Settings(database_url=URL, _env_file=None, **kw)  # type: ignore[call-arg]


def test_defaults_are_fakes_and_fine_outside_prod() -> None:
    s = _s()
    assert (s.whatsapp_provider, s.gmail_provider, s.storage_backend) == ("fake", "fake", "local")
    assert_production_safe(s)


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"whatsapp_provider": "fake"}, "whatsapp_provider"),
        ({"gmail_provider": "fake"}, "gmail_provider"),
        ({"storage_backend": "local"}, "storage_backend"),
        ({"storage_backend": "memory"}, "storage_backend"),
        ({"whatsapp_app_secret": None}, "whatsapp_app_secret"),
        ({"gmail_pubsub_audience": None}, "gmail_pubsub_audience"),
        ({"whatsapp_api_base_url": None}, "whatsapp_api_base_url"),
        ({"s3_bucket": None}, "s3_bucket"),
        ({"llm_model": "fake"}, "llm_model"),
        ({"drive_provider": "fake"}, "drive_provider"),
        ({"drive_credentials_file": None}, "drive_credentials_file"),
        ({"openai_api_key": None}, "openai_api_key"),
        ({"gmail_credentials_file": Path("/nonexistent/gmail.json")}, "gmail_credentials_file"),
        ({"gmail_credentials_file": Path(".")}, "gmail_credentials_file"),
    ],
)
def test_prod_refuses_unsafe(override: dict[str, Any], fragment: str) -> None:
    with pytest.raises(UnsafeConfigurationError, match=fragment):
        assert_production_safe(_s(env="prod", **{**REAL, **override}))


def test_prod_with_real_providers_is_safe() -> None:
    assert_production_safe(_s(env="prod", **REAL))


def test_all_problems_reported_at_once() -> None:
    with pytest.raises(UnsafeConfigurationError) as exc:
        assert_production_safe(_s(env="prod"))
    for name in ("whatsapp_provider", "gmail_provider", "storage_backend"):
        assert name in str(exc.value)


def test_llm_defaults_to_fake() -> None:
    assert _s().llm_model == "fake"


def test_non_openai_model_needs_no_openai_key() -> None:
    assert_production_safe(
        _s(env="prod", **{**REAL, "llm_model": "mistral:mistral-large-latest", "openai_api_key": None})
    )

from pathlib import Path
from typing import Any

import pytest

from app.core.settings import Settings
from app.core.startup import UnsafeConfigurationError, assert_production_safe, production_problems

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
    "embedding_model": "openai:text-embedding-3-small",
    "openai_api_key": "sk-test",
    "drive_provider": "google",
    "price_source": "competitors",
    "brixx_provider": "api",
    "brixx_token": "brixx-test",
    "dashboard_auth_provider": "google",
    "dashboard_session_secret": "x" * 32,
    "google_oauth_client_id": "client.apps.googleusercontent.com",
    "google_chat_provider": "google",
    "google_chat_project_number": "123456789",
    "frontend_base_url": "https://dash.estateos.example",
    "google_login_redirect_uri": "https://api.estateos.example/api/auth/login/google/callback",
    "google_oauth_redirect_uri": "https://api.estateos.example/api/auth/google/callback",
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
        ({"embedding_model": "fake"}, "embedding_model"),
        ({"drive_provider": "fake"}, "drive_provider"),
        ({"price_source": "fake"}, "price_source"),
        ({"dashboard_auth_provider": "fake"}, "dashboard_auth_provider"),
        ({"dashboard_session_secret": None}, "dashboard_session_secret"),
        ({"dashboard_session_secret": "short"}, "dashboard_session_secret"),
        ({"dashboard_session_secret": "dev-only-session-secret-change-me-32-chars"}, "public dev-only default"),
        ({"dashboard_session_secret": "DEV-ONLY-" + "x" * 30}, "public dev-only default"),
        ({"google_oauth_client_id": None}, "google_oauth_client_id"),
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
        _s(
            env="prod",
            **{
                **REAL,
                "llm_model": "mistral:mistral-large-latest",
                "embedding_model": "cohere:embed-multilingual-v3.0",
                "openai_api_key": None,
            },
        )
    )


def test_gemini_model_needs_its_key() -> None:
    gemini = {
        **REAL,
        "llm_model": "google-gla:gemini-2.5-flash",
        "embedding_model": "google-gla:gemini-embedding-001",
        "openai_api_key": None,
    }
    with pytest.raises(UnsafeConfigurationError, match="gemini_api_key"):
        assert_production_safe(_s(env="prod", **gemini))
    assert_production_safe(_s(env="prod", **{**gemini, "gemini_api_key": "g-test"}))


def test_an_openai_embedding_model_needs_the_openai_key() -> None:
    with pytest.raises(UnsafeConfigurationError, match="embedding_model is an openai model"):
        assert_production_safe(_s(env="prod", **{**REAL, "llm_model": "google-gla:gemini-2.5-flash",
                                                 "gemini_api_key": "g", "openai_api_key": None}))  # fmt: skip


@pytest.mark.parametrize("field", ["frontend_base_url", "google_login_redirect_uri", "google_oauth_redirect_uri"])
@pytest.mark.parametrize("bad", ["http://localhost:3000", "http://dash.estateos.example", "https://127.0.0.1:3000", ""])
def test_prod_refuses_a_local_or_plain_http_public_url(field: str, bad: str) -> None:
    problems = production_problems(_s(env="prod", **{**REAL, field: bad}))
    assert any(p.startswith(f"{field} must be a public https URL") for p in problems)


def test_prod_accepts_public_https_urls() -> None:
    assert production_problems(_s(env="prod", **REAL)) == []


def test_prod_refuses_the_fake_google_chat_provider_which_accepts_unsigned_tokens() -> None:
    problems = production_problems(_s(env="prod", **{**REAL, "google_chat_provider": "fake"}))
    assert any(p.startswith("google_chat_provider is 'fake'") for p in problems)


def test_prod_needs_the_google_chat_audience_when_the_provider_is_real() -> None:
    problems = production_problems(_s(env="prod", **{**REAL, "google_chat_project_number": None}))
    assert any(p.startswith("google_chat_project_number is not set") for p in problems)

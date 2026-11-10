"""Every setting the dashboard work introduced is documented in .env.example and forwarded by docker/compose.yml."""

import re
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.sender.settings import SenderSettings

ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_SETTINGS = [
    "dashboard_auth_provider",
    "dashboard_session_secret",
    "dashboard_session_ttl_min",
    "dashboard_trust_forwarded_for",
    "dashboard_cors_origins",
    "google_oauth_client_id",
    "frontend_base_url",
    "dashboard_cookie_domain",
    "google_login_redirect_uri",
    "tenant_sends_per_hour",
    "concierge_daily_cap",
    "concierge_daily_budget_usd",
]
DASHBOARD_SENDER_SETTINGS = ["gmail_reply_send_credentials_file"]


def _names(path: str, pattern: str) -> set[str]:
    return set(re.findall(pattern, (ROOT / path).read_text(), flags=re.M))


@pytest.mark.parametrize("field", DASHBOARD_SETTINGS + DASHBOARD_SENDER_SETTINGS)
def test_dashboard_settings_are_in_env_example(field: str) -> None:
    assert field in Settings.model_fields or field in SenderSettings.model_fields
    assert field.upper() in _names(".env.example", r"^([A-Z][A-Z0-9_]*)=")


@pytest.mark.parametrize("field", DASHBOARD_SETTINGS + DASHBOARD_SENDER_SETTINGS)
def test_dashboard_settings_are_forwarded_by_compose(field: str) -> None:
    assert field.upper() in _names("docker/compose.yml", r"^\s+([A-Z][A-Z0-9_]*):")

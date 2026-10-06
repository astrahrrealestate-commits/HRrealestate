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
}


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

from typing import Any

import pytest
from pydantic import SecretStr

from app.core.errors import EstateOSError
from app.core.settings import Settings
from app.core.startup import production_problems

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def _s(**kw: Any) -> Settings:
    return Settings(database_url=URL, _env_file=None, **kw)  # type: ignore[call-arg]


def test_dashboard_defaults() -> None:
    s = _s()
    assert s.dashboard_auth_provider == "fake"
    assert s.dashboard_session_secret is None
    assert s.dashboard_session_ttl_min == 480
    assert s.google_oauth_client_id is None


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"dashboard_auth_provider": "fake"}, "dashboard_auth_provider"),
        ({"dashboard_session_secret": None}, "dashboard_session_secret"),
        ({"dashboard_session_secret": SecretStr("x" * 31)}, "dashboard_session_secret"),
        ({"google_oauth_client_id": None}, "google_oauth_client_id"),
    ],
)
def test_prod_dashboard_problems(override: dict[str, Any], fragment: str) -> None:
    base: dict[str, Any] = {
        "dashboard_auth_provider": "google",
        "dashboard_session_secret": SecretStr("x" * 32),
        "google_oauth_client_id": "c.apps.googleusercontent.com",
    }
    problems = production_problems(_s(env="prod", **{**base, **override}))
    assert any(fragment in p for p in problems)


def test_prod_dashboard_failure_is_estateos_error() -> None:
    from app.core.startup import assert_production_safe

    with pytest.raises(EstateOSError, match="dashboard_auth_provider"):
        assert_production_safe(_s(env="prod"))

from typing import Any

import pytest

from app.core.errors import BrixxAuthError, BrixxError, EstateOSError
from app.core.settings import Settings
from app.core.startup import production_problems

URL = "postgresql+psycopg://u:p@localhost:5433/db"


def _s(**kw: Any) -> Settings:
    return Settings(_env_file=None, **{"database_url": URL, **kw})


def _brixx(problems: list[str]) -> list[str]:
    return [p for p in problems if "brixx" in p]


def test_brixx_defaults() -> None:
    s = _s()
    assert s.brixx_provider == "fake"
    assert s.brixx_base_url == "https://mob.brixxonline.com/api/v1"
    assert s.brixx_environment == "hrrealestate"
    assert s.brixx_token is None
    assert s.brixx_auth_scheme == "bearer"
    assert s.brixx_sync_interval_minutes == 15
    assert s.brixx_timeout_sec == 60.0


def test_brixx_token_is_a_secret() -> None:
    assert "tok-123" not in repr(_s(brixx_token="tok-123"))


def test_prod_refuses_fake_brixx_provider() -> None:
    problems = production_problems(_s(env="prod", brixx_provider="fake"))
    assert "brixx_provider is 'fake'" in problems


def test_prod_refuses_api_brixx_without_token() -> None:
    problems = production_problems(_s(env="prod", brixx_provider="api"))
    assert "brixx_token is not set" in problems
    assert "brixx_provider is 'fake'" not in problems


def test_prod_accepts_api_brixx_with_token() -> None:
    assert _brixx(production_problems(_s(env="prod", brixx_provider="api", brixx_token="tok"))) == []


def test_dev_defaults_have_no_brixx_problems() -> None:
    assert _brixx(production_problems(_s())) == []


@pytest.mark.parametrize("interval", [0, -1])
def test_sync_interval_must_be_positive(interval: int) -> None:
    with pytest.raises(ValueError):
        _s(brixx_sync_interval_minutes=interval)


def test_brixx_errors_hierarchy() -> None:
    assert issubclass(BrixxError, EstateOSError)
    assert issubclass(BrixxAuthError, BrixxError)

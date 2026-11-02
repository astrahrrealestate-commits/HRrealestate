from typing import Any

import pytest
from pydantic import SecretStr

from app.channels.brixx.fake import FakeBrixxApi
from app.channels.brixx.http import HttpBrixxApi
from app.channels.registry import brixx_api
from app.core.errors import BrixxAuthError, BrixxError, UnsafeConfigurationError
from app.core.settings import Settings

TOKEN = "s3cr3t-token-value"


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def test_fake_provider_builds_fake() -> None:
    assert isinstance(brixx_api(_s()), FakeBrixxApi)


def test_api_provider_builds_http_adapter() -> None:
    api = brixx_api(_s(brixx_provider="api", brixx_token=SecretStr(TOKEN)))
    assert isinstance(api, HttpBrixxApi)


def test_api_provider_needs_token() -> None:
    with pytest.raises(UnsafeConfigurationError) as exc:
        brixx_api(_s(brixx_provider="api"))
    assert "brixx_token" in str(exc.value)


def test_api_provider_rejects_http_base_url() -> None:
    settings = _s(brixx_provider="api", brixx_token=SecretStr(TOKEN), brixx_base_url="http://brixx.test/api")
    with pytest.raises(BrixxError) as exc:
        brixx_api(settings)
    assert TOKEN not in str(exc.value)


def test_auth_error_message_never_contains_token() -> None:
    assert TOKEN not in str(BrixxAuthError("BRIXX rejected the token (HTTP 401)"))

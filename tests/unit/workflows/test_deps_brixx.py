from collections.abc import Iterator

import pytest

from app.channels.brixx.fake import FakeBrixxApi
from app.core.settings import Settings
from app.workflows import deps


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    deps.set_brixx_api(None)
    deps._default_brixx.cache_clear()
    yield
    deps.set_brixx_api(None)
    deps._default_brixx.cache_clear()


def test_brixx_api_defaults_to_cached_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    api = deps.brixx_api()
    assert isinstance(api, FakeBrixxApi)
    assert deps.brixx_api() is api


def test_brixx_api_override() -> None:
    mine = FakeBrixxApi({})
    deps.set_brixx_api(mine)
    assert deps.brixx_api() is mine

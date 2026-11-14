from pathlib import Path
from typing import Any

import pytest

from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings
from app.storage.factory import build_storage
from app.storage.local import LocalStorage
from app.storage.memory import MemoryStorage
from app.storage.s3 import S3Storage


def _s(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@h/db", _env_file=None, **kw)  # type: ignore[call-arg]


def test_local_and_memory(tmp_path: Path) -> None:
    assert isinstance(build_storage(_s(storage_backend="local", storage_local_dir=tmp_path)), LocalStorage)
    assert isinstance(build_storage(_s(storage_backend="memory")), MemoryStorage)


def test_s3_requires_bucket() -> None:
    with pytest.raises(UnsafeConfigurationError, match="s3_bucket"):
        build_storage(_s(storage_backend="s3"))


def test_s3_builds_client_without_network() -> None:
    storage = build_storage(_s(storage_backend="s3", s3_bucket="b", s3_access_key_id="k", s3_secret_access_key="s"))
    assert isinstance(storage, S3Storage)

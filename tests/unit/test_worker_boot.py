"""The worker builds its ingestion dependencies before launching DBOS: bad config fails at boot, not in step one."""

import pytest

import app.worker
from app.core.errors import UnsafeConfigurationError
from app.core.settings import Settings


def test_worker_refuses_to_launch_when_dependencies_cannot_be_built(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> None:
        raise UnsafeConfigurationError("storage_backend 's3' needs s3_bucket")

    def launched(*_a: object, **_k: object) -> None:
        raise AssertionError("DBOS launched despite broken dependencies")

    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(app.worker, "get_settings", lambda: settings)
    monkeypatch.setattr(app.worker, "get_deps", broken)
    monkeypatch.setattr(app.worker, "launch", launched)
    with pytest.raises(UnsafeConfigurationError, match="s3_bucket"):
        app.worker.main([])

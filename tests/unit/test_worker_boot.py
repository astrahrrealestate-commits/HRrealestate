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


def test_worker_boot_registers_finance_queue() -> None:
    """Quote checks and snapshots run on their own queue, at most 2 per worker (each is mostly one model call)."""
    from unittest.mock import patch

    from app.core.workflow_names import FINANCE_QUEUE
    from app.workflows import queues

    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[call-arg]
    with patch.object(queues.DBOS, "register_queue", side_effect=lambda name, **kw: f"queue:{name}") as reg:
        queues.register_queues(settings)
    options = {c.args[0]: c.kwargs for c in reg.call_args_list}
    assert FINANCE_QUEUE == "finance"
    assert options["finance"] == {"worker_concurrency": 2}
    assert queues.finance_queue() == "queue:finance"  # type: ignore[comparison-overlap]

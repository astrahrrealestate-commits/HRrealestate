"""Queue registration at worker boot: every queue enqueuers name is registered, the chat queue from settings."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core import workflow_names
from app.core.settings import Settings
from app.workflows import queues


def _settings(**kw: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None, **kw)  # type: ignore[arg-type]


def _register(settings: Settings) -> dict[str, dict[str, Any]]:
    with patch.object(queues.DBOS, "register_queue", side_effect=lambda name, **kw: MagicMock(name=name)) as reg:
        queues.register_queues(settings)
    return {c.args[0]: c.kwargs for c in reg.call_args_list}


def test_every_named_queue_is_registered_at_boot() -> None:
    registered = _register(_settings())
    assert set(registered) == {
        "pipeline",
        "gmail_sync",
        "timers",
        "documents",
        "concierge",
        "brixx",
        "brixx_documents",
        "finance",
    }
    names = {v for k, v in vars(workflow_names).items() if k.endswith("_QUEUE")}
    assert names == set(registered)


def test_the_chat_queue_is_named_once_and_shared() -> None:
    assert workflow_names.CONCIERGE_QUEUE == queues.CONCIERGE_QUEUE == "concierge"


def test_the_chat_queue_polls_fast_with_concurrency_from_settings() -> None:
    assert _register(_settings())["concierge"] == {
        "worker_concurrency": 4,
        "polling_interval_sec": queues.CONCIERGE_POLL_SECONDS,
    }
    assert queues.CONCIERGE_POLL_SECONDS == 0.25
    assert _register(_settings(concierge_worker_concurrency=2))["concierge"]["worker_concurrency"] == 2


def test_other_queues_keep_their_options() -> None:
    registered = _register(_settings())
    assert registered["pipeline"] == {"worker_concurrency": queues.PIPELINE_WORKER_CONCURRENCY}
    assert registered["gmail_sync"] == {"concurrency": 1}
    assert registered["timers"] == {"worker_concurrency": 2}
    assert registered["documents"] == {"partition_concurrency": 1}
    assert registered["brixx"] == {"worker_concurrency": 16}
    assert registered["brixx_documents"] == {"concurrency": 3}  # three BRIXX downloads at a time, across workers


def test_the_chat_queue_handle_is_the_registered_one() -> None:
    with patch.object(queues.DBOS, "register_queue", side_effect=lambda name, **kw: f"queue:{name}"):
        queues.register_queues(_settings())
    assert queues.concierge_queue() == "queue:concierge"  # type: ignore[comparison-overlap]


def test_an_unregistered_queue_is_a_clear_error() -> None:
    with patch.dict(queues._handles, clear=True), pytest.raises(RuntimeError, match="not registered"):
        queues.concierge_queue()


@pytest.mark.parametrize("bad", [0, -1])
def test_concurrency_setting_must_be_positive(bad: int) -> None:
    with pytest.raises(ValueError):
        _settings(concierge_worker_concurrency=bad)

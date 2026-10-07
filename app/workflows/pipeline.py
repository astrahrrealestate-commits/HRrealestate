"""Pipeline entry DBOS workflow: triage inbound messages, link cases, propose actions."""

from typing import Any
from uuid import UUID

from dbos import DBOS

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import PIPELINE_ENTRY
from app.ingestion.process import is_transient
from app.pipeline.understand import understand_message
from app.workflows.deps import get_engine

log = get_logger(__name__)


def _retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc)


_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 5,
    "interval_seconds": 2.0,
    "backoff_rate": 2.0,
    "should_retry": _retryable,
}


@DBOS.step(name="pipeline.understand", **_RETRY)
def understand_step(message_id: str) -> str:
    engine = get_engine()
    settings = get_settings()
    res = understand_message(engine, settings, UUID(message_id))
    return "understood" if res is not None else "failed"


@DBOS.workflow(name=PIPELINE_ENTRY)
def pipeline_entry(message_id: str) -> str:
    status = understand_step(message_id)
    log.info("pipeline.entry.done", message_id=message_id, status=status)
    return status

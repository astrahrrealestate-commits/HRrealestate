"""One retry policy for workflow steps that call providers (WhatsApp, Gmail, Drive, LLM) or the database.

Retried: errors that say so (`retryable`), and transient infrastructure, LLM and Drive errors. Not retried: data and
contract problems, and sends that may already have been delivered (`maybe_sent` keeps `retryable` False).
"""

from typing import Any

from app.ingestion.process import is_transient
from app.llm.calls import is_transient as llm_transient
from app.storage.drive import is_transient as drive_transient


def retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False)) or is_transient(exc) or llm_transient(exc) or drive_transient(exc)


STEP_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 6,
    "interval_seconds": 2.0,
    "backoff_rate": 2.0,  # ~1 minute in total, then the step fails and the workflow records it
    "should_retry": retryable,
}

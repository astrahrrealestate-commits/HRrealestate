"""Shared by the BRIXX workflows (table sync, document downloads): step retry policy and step-result helpers."""

from typing import Any

from sqlalchemy.exc import DBAPIError

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError, StaleRunError

OK = "ok"
FAILED = "failed:"
_NOT_RETRIED = (BrixxAuthError, StaleRunError)


def brixx_retryable(exc: BaseException) -> bool:
    """Retry BRIXX and database errors, except those where another attempt cannot succeed."""
    return isinstance(exc, BrixxError | DBAPIError) and not isinstance(exc, _NOT_RETRIED)


BRIXX_RETRY: dict[str, Any] = {
    "retries_allowed": True,
    "max_attempts": 8,
    "interval_seconds": 5.0,
    "backoff_rate": 2.0,
    "should_retry": brixx_retryable,
}


def error_name(exc: BaseException) -> str:
    """Class name of the error that mattered (the last attempt's, when DBOS gave up retrying)."""
    attempts = getattr(exc, "errors", None) if type(exc).__name__ == "DBOSMaxStepRetriesExceeded" else None
    return type(attempts[-1]).__name__ if attempts else type(exc).__name__


def info_from_json(data: dict[str, Any]) -> BrixxTable:
    """The `BrixxTable` a step returned as `dataclasses.asdict` (step outputs are JSON)."""
    return BrixxTable(data["name"], data["primary_key"], tuple(BrixxField(**f) for f in data["fields"]))

"""What Google refused, as the error the owner reads. Logs the type, status and reason codes, never the body."""

import json

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from app.channels.calendar.ports import (
    ACCESS_REFUSED,
    NO_ANSWER,
    REJECTED,
    SIGN_IN_EXPIRED,
    CalendarUnavailableError,
)
from app.core.logging import get_logger

log = get_logger(__name__)

_BUSY_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"})


def http_status(exc: Exception) -> int | None:
    return int(exc.resp.status) if isinstance(exc, HttpError) else None


def _reasons(exc: Exception) -> list[str]:
    if not isinstance(exc, HttpError):
        return []
    try:
        return [str(e.get("reason", "")) for e in json.loads(exc.content)["error"]["errors"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        return []


def _message(exc: Exception, status: int | None, reasons: list[str]) -> str:
    if isinstance(exc, RefreshError):
        return NO_ANSWER if exc.retryable else SIGN_IN_EXPIRED
    if status == 401:
        return SIGN_IN_EXPIRED
    if status is None or status == 429 or status >= 500 or _BUSY_REASONS.intersection(reasons):
        return NO_ANSWER
    return ACCESS_REFUSED if status == 403 else REJECTED


def unavailable(operation: str, exc: Exception) -> CalendarUnavailableError:
    status, reasons = http_status(exc), _reasons(exc)
    log.warning(
        "google_calendar.call_failed", operation=operation, error=type(exc).__name__, status=status, reasons=reasons
    )
    return CalendarUnavailableError(_message(exc, status, reasons))

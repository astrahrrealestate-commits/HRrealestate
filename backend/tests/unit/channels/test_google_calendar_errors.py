"""A Google refusal is named for what it is: an expired sign-in or a missing permission is not "not connected",
and a failed read is never an empty or free calendar."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from structlog.testing import capture_logs

from app.channels.calendar import CalendarAttendee, CalendarEventCreate, CalendarUnavailableError
from app.channels.calendar.google import GoogleCalendarClient
from app.channels.calendar.ports import ACCESS_REFUSED, NO_ANSWER, REJECTED, SIGN_IN_EXPIRED

START = datetime(2026, 11, 27, 14, tzinfo=UTC)
END = START + timedelta(hours=1)


def _http_error(status: int, reason: str = "") -> HttpError:
    body = json.dumps({"error": {"errors": [{"reason": reason}], "message": "guest@example.test"}}).encode()
    return HttpError(httplib2.Response({"status": status}), body)


def _failing(exc: Exception) -> GoogleCalendarClient:
    service = MagicMock()
    events = service.events()
    for call in (service.freebusy().query, events.list, events.insert, events.patch, events.delete, events.get):
        call.return_value.execute.side_effect = exc
    return GoogleCalendarClient(service=service)


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (RefreshError("invalid_grant"), SIGN_IN_EXPIRED),
        (_http_error(401), SIGN_IN_EXPIRED),
        (_http_error(403), ACCESS_REFUSED),
        (_http_error(500), NO_ANSWER),
        (TimeoutError(), NO_ANSWER),
        (_http_error(403, "rateLimitExceeded"), NO_ANSWER),
        (_http_error(403, "userRateLimitExceeded"), NO_ANSWER),
        (_http_error(403, "quotaExceeded"), NO_ANSWER),
        (_http_error(429), NO_ANSWER),
        (_http_error(400), REJECTED),
        (RefreshError("temporary", retryable=True), NO_ANSWER),
    ],
)
def test_free_busy_failure_names_the_cause(exc: Exception, message: str) -> None:
    with pytest.raises(CalendarUnavailableError) as caught:
        _failing(exc).check_free_busy(START, END)
    assert str(caught.value) == message


def test_a_failed_event_list_is_an_error_not_an_empty_calendar() -> None:
    with pytest.raises(CalendarUnavailableError) as caught:
        _failing(_http_error(403)).list_events(START, END)
    assert str(caught.value) == ACCESS_REFUSED


def test_a_failed_create_is_a_calendar_error() -> None:
    event = CalendarEventCreate(
        title="Visit", start_time=START, end_time=END, attendees=[CalendarAttendee(email="a@example.test")]
    )
    with pytest.raises(CalendarUnavailableError) as caught:
        _failing(RefreshError("invalid_grant")).create_event(event)
    assert str(caught.value) == SIGN_IN_EXPIRED


@pytest.mark.parametrize("calendars", [{"primary": {"errors": [{"reason": "notFound"}], "busy": []}}, {}])
def test_a_free_busy_answer_without_a_readable_calendar_is_not_a_free_slot(calendars: dict[str, object]) -> None:
    service = MagicMock()
    service.freebusy().query.return_value.execute.return_value = {"calendars": calendars}
    with pytest.raises(CalendarUnavailableError):
        GoogleCalendarClient(service=service).check_free_busy(START, END)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.delete_event("g1"),
        lambda c: c.update_event("g1", {"summary": "x"}),
        lambda c: c.respond_to_invite("g1", "accepted"),
    ],
)
def test_a_refused_change_is_an_error_not_a_silent_success(call: Callable[[GoogleCalendarClient], object]) -> None:
    with pytest.raises(CalendarUnavailableError) as caught:
        call(_failing(RefreshError("invalid_grant")))
    assert str(caught.value) == SIGN_IN_EXPIRED


@pytest.mark.parametrize("status", [404, 410])
def test_deleting_an_event_that_is_already_gone_succeeds(status: int) -> None:
    assert _failing(_http_error(status)).delete_event("g1") is True


def test_the_log_carries_no_google_response_body() -> None:
    with capture_logs() as logs, pytest.raises(CalendarUnavailableError):
        _failing(_http_error(403, "forbidden")).create_event(
            CalendarEventCreate(title="v", start_time=START, end_time=END)
        )
    assert "guest@example.test" not in repr(logs)

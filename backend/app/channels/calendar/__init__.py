"""Calendar channel exports and factory."""

from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.channels import google_store
from app.channels.calendar.fake import FakeCalendarClient
from app.channels.calendar.google import GoogleCalendarClient
from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    CalendarEvent,
    CalendarEventCreate,
    CalendarUnavailableError,
    TimeSlot,
)
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


def _google_client() -> GoogleCalendarClient | None:
    """The live client when `calendar_provider == "google"` and its token file exists, else None."""

    settings = get_settings()

    unified = google_store.refresh(settings)  # the owner's connected Google account, shared across processes

    cred_file = unified if unified.exists() else settings.calendar_credentials_file

    if (settings.calendar_provider != "google" and not unified.exists()) or cred_file is None or not cred_file.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(cred_file))

    return GoogleCalendarClient(service=build("calendar", "v3", credentials=creds, cache_discovery=False))


def get_calendar_client(credentials: dict[str, Any] | None = None) -> CalendarClientProtocol:
    """The live Google Calendar client. Raises `CalendarUnavailableError` when none is connected: there is no fake
    fallback, so a missing calendar is never read as "free" and no event is ever pretended saved."""

    try:
        live = _google_client()
    except Exception as exc:  # unreadable settings or token
        log.warning("calendar.google_client_unavailable", error=type(exc).__name__)
        raise CalendarUnavailableError("Google Calendar is not connected") from exc

    if live is not None:
        return live
    if credentials and "service" in credentials:
        return GoogleCalendarClient(service=credentials["service"])
    raise CalendarUnavailableError("Google Calendar is not connected")


__all__ = [
    "CalendarAttendee",
    "CalendarClientProtocol",
    "CalendarEvent",
    "CalendarEventCreate",
    "CalendarUnavailableError",
    "FakeCalendarClient",
    "GoogleCalendarClient",
    "TimeSlot",
    "get_calendar_client",
]

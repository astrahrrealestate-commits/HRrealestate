"""Calendar channel exports and factory."""

from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.channels.calendar.fake import FakeCalendarClient
from app.channels.calendar.google import GoogleCalendarClient
from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    CalendarEvent,
    CalendarEventCreate,
    TimeSlot,
)
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)
_global_fake_client: FakeCalendarClient | None = None


def _google_client() -> GoogleCalendarClient | None:
    """The live client when `calendar_provider == "google"` and its token file exists, else None."""
    settings = get_settings()
    cred_file = settings.calendar_credentials_file
    if settings.calendar_provider != "google" or cred_file is None or not cred_file.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(cred_file))
    return GoogleCalendarClient(service=build("calendar", "v3", credentials=creds, cache_discovery=False))


def get_calendar_client(credentials: dict[str, Any] | None = None) -> CalendarClientProtocol:
    """Returns live GoogleCalendarClient if configured, otherwise singleton FakeCalendarClient."""
    global _global_fake_client
    try:
        live = _google_client()
    except Exception as exc:  # unreadable settings or token: fall back to the fake, but say why
        log.warning("calendar.google_client_unavailable", error=type(exc).__name__)
        live = None
    if live is not None:
        return live
    if credentials and "service" in credentials:
        return GoogleCalendarClient(service=credentials["service"])
    if _global_fake_client is None:
        _global_fake_client = FakeCalendarClient(credentials=credentials)
    return _global_fake_client


__all__ = [
    "CalendarAttendee",
    "CalendarClientProtocol",
    "CalendarEvent",
    "CalendarEventCreate",
    "FakeCalendarClient",
    "GoogleCalendarClient",
    "TimeSlot",
    "get_calendar_client",
]

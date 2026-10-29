"""Calendar channel exports and factory."""

from app.channels.calendar.fake import FakeCalendarClient
from app.channels.calendar.google import GoogleCalendarClient
from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    CalendarEvent,
    CalendarEventCreate,
    TimeSlot,
)

_global_fake_client: FakeCalendarClient | None = None


def get_calendar_client(credentials: dict | None = None) -> CalendarClientProtocol:
    """Returns live GoogleCalendarClient if configured, otherwise singleton FakeCalendarClient."""
    global _global_fake_client
    try:
        from pathlib import Path
        from app.core.settings import get_settings
        settings = get_settings()
        if getattr(settings, "calendar_provider", "fake") == "google" and getattr(settings, "calendar_credentials_file", None):
            cred_file = Path(settings.calendar_credentials_file)
            if cred_file.exists():
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build
                creds = Credentials.from_authorized_user_file(str(cred_file))
                service = build("calendar", "v3", credentials=creds, cache_discovery=False)
                return GoogleCalendarClient(service=service)
    except Exception:
        pass

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


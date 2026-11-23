"""Calendar integration ports: protocol and models for Google Calendar sync."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.core.errors import EstateOSError


class CalendarUnavailableError(EstateOSError):
    """Google Calendar is not connected or did not answer. We never assume a free calendar or a saved event."""


@dataclass(frozen=True)
class TimeSlot:
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True)
class CalendarAttendee:
    email: str
    display_name: str | None = None
    response_status: str = "needsAction"  # needsAction, accepted, declined, tentative


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime
    location: str | None = None
    status: str = "confirmed"  # confirmed, tentative, cancelled
    attendees: list[CalendarAttendee] = field(default_factory=list)
    html_link: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    organizer_email: str | None = None
    organizer_name: str | None = None
    self_response_status: str | None = None  # the connected owner's own RSVP; None when they are not an attendee


INVITE_RESPONSES = ("accepted", "declined", "tentative")


@dataclass(frozen=True)
class CalendarEventCreate:
    title: str
    start_time: datetime
    end_time: datetime
    description: str | None = None
    location: str | None = None
    attendees: list[CalendarAttendee] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CalendarClientProtocol(Protocol):
    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """List events in the specified datetime window."""
        ...

    def check_free_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        """Return busy slots within the given window."""
        ...

    def create_event(self, event: CalendarEventCreate) -> CalendarEvent:
        """Create a new event in Google Calendar."""
        ...

    def update_event(self, event_id: str, updates: dict[str, Any]) -> CalendarEvent:
        """Update an existing event."""
        ...

    def delete_event(self, event_id: str) -> bool:
        """Delete an event by its external calendar ID."""
        ...

    def list_pending_invites(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Events someone else organised where the owner's own RSVP is still `needsAction`."""
        ...

    def respond_to_invite(self, event_id: str, response: str) -> CalendarEvent | None:
        """Set the owner's RSVP (`accepted`, `declined`, `tentative`); None when the event is not an open invite."""
        ...

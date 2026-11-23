"""Fake Google Calendar client for testing and offline development.

Emits realistic Google Calendar API shapes and tracks events in-memory.
Operates with mock credentials without making any network calls.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.channels.calendar.ports import (
    CalendarClientProtocol,
    CalendarEvent,
    CalendarEventCreate,
    TimeSlot,
)


class FakeCalendarClient(CalendarClientProtocol):
    """In-memory Google Calendar simulator supporting free/busy calculation and CRUD."""

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self.credentials = credentials or {
            "type": "service_account",
            "project_id": "estateos-fake-dev",
            "private_key_id": "fake_key_001",
            "client_email": "calendar-bot@estateos-fake-dev.iam.gserviceaccount.com",
            "client_id": "fake_google_client_id_12345",
        }
        self._events: dict[str, CalendarEvent] = {}

    def seed_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        location: str | None = None,
        description: str | None = None,
        event_id: str | None = None,
        organizer_email: str | None = None,
        organizer_name: str | None = None,
        self_response_status: str | None = None,
    ) -> CalendarEvent:
        """Helper to seed calendar with prior existing bookings for conflict testing."""
        eid = event_id or f"gcal_evt_{uuid4().hex[:12]}"
        evt = CalendarEvent(
            id=eid,
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location,
            status="confirmed",
            html_link=f"https://calendar.google.com/calendar/event?eid={eid}",
            created_at=datetime.now(UTC),
            organizer_email=organizer_email,
            organizer_name=organizer_name,
            self_response_status=self_response_status,
        )
        self._events[eid] = evt
        return evt

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Return events overlapping [start, end]."""
        results: list[CalendarEvent] = []
        for evt in self._events.values():
            if evt.status == "cancelled":
                continue
            # Overlap check: evt.start < end and evt.end > start
            if evt.start_time < end and evt.end_time > start:
                results.append(evt)
        # Sort by start_time
        results.sort(key=lambda e: e.start_time)
        return results

    def check_free_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        """Return busy slots within [start, end]."""
        overlapping = self.list_events(start, end)
        return [TimeSlot(start_time=e.start_time, end_time=e.end_time) for e in overlapping]

    def create_event(self, event: CalendarEventCreate) -> CalendarEvent:
        """Create a new event and return Google-formatted event object."""
        eid = f"gcal_evt_{uuid4().hex[:12]}"
        created = CalendarEvent(
            id=eid,
            title=event.title,
            description=event.description,
            start_time=event.start_time,
            end_time=event.end_time,
            location=event.location,
            status="confirmed",
            attendees=list(event.attendees),
            html_link=f"https://calendar.google.com/calendar/event?eid={eid}",
            created_at=datetime.now(UTC),
            metadata=dict(event.metadata),
        )
        self._events[eid] = created
        return created

    def update_event(self, event_id: str, updates: dict[str, Any]) -> CalendarEvent:
        """Update an existing event."""
        if event_id not in self._events:
            raise KeyError(f"Event {event_id} not found in FakeCalendarClient")

        curr = self._events[event_id]
        updated = CalendarEvent(
            id=curr.id,
            title=updates.get("title", curr.title),
            description=updates.get("description", curr.description),
            start_time=updates.get("start_time", curr.start_time),
            end_time=updates.get("end_time", curr.end_time),
            location=updates.get("location", curr.location),
            status=updates.get("status", curr.status),
            attendees=updates.get("attendees", curr.attendees),
            html_link=curr.html_link,
            created_at=curr.created_at,
            metadata={**curr.metadata, **updates.get("metadata", {})},
            organizer_email=curr.organizer_email,
            organizer_name=curr.organizer_name,
            self_response_status=updates.get("self_response_status", curr.self_response_status),
        )
        self._events[event_id] = updated
        return updated

    def delete_event(self, event_id: str) -> bool:
        """Mark event as cancelled or remove from store."""
        if event_id in self._events:
            curr = self._events[event_id]
            self._events[event_id] = CalendarEvent(
                id=curr.id,
                title=curr.title,
                description=curr.description,
                start_time=curr.start_time,
                end_time=curr.end_time,
                location=curr.location,
                status="cancelled",
                attendees=curr.attendees,
                html_link=curr.html_link,
                created_at=curr.created_at,
                metadata=curr.metadata,
                organizer_email=curr.organizer_email,
                organizer_name=curr.organizer_name,
                self_response_status=curr.self_response_status,
            )
            return True
        return False

    def list_pending_invites(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Seeded events whose owner RSVP is still `needsAction`."""
        return [e for e in self.list_events(start, end) if e.self_response_status == "needsAction"]

    def respond_to_invite(self, event_id: str, response: str) -> CalendarEvent | None:
        """Record the owner's RSVP; None when the event is unknown or not an open invite."""
        curr = self._events.get(event_id)
        if curr is None or curr.status == "cancelled" or curr.self_response_status is None:
            return None
        return self.update_event(event_id, {"self_response_status": response})

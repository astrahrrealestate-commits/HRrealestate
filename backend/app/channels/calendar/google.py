"""Production Google Calendar API adapter with automatic fallback to FakeCalendarClient."""

from datetime import UTC, datetime
from typing import Any

from googleapiclient.errors import HttpError

from app.channels.calendar.fake import FakeCalendarClient
from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    CalendarEvent,
    CalendarEventCreate,
    TimeSlot,
)
from app.core.logging import get_logger

log = get_logger(__name__)

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]


def _to_event(item: dict[str, Any], default_start: datetime, default_end: datetime) -> CalendarEvent:
    """One Google Calendar API event resource as a `CalendarEvent`, with who organised it and the owner's own RSVP."""
    start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
    end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
    organizer = item.get("organizer") or {}
    attendees = [
        CalendarAttendee(
            email=a.get("email", ""),
            display_name=a.get("displayName"),
            response_status=a.get("responseStatus", "needsAction"),
        )
        for a in item.get("attendees", [])
    ]
    own = next((a for a in item.get("attendees", []) if a.get("self")), None)
    return CalendarEvent(
        id=item["id"],
        title=item.get("summary", "Untitled"),
        description=item.get("description"),
        start_time=datetime.fromisoformat(start_raw) if start_raw else default_start,
        end_time=datetime.fromisoformat(end_raw) if end_raw else default_end,
        location=item.get("location"),
        status=item.get("status", "confirmed"),
        attendees=attendees,
        html_link=item.get("htmlLink"),
        organizer_email=None if organizer.get("self") else organizer.get("email"),
        organizer_name=organizer.get("displayName"),
        self_response_status=own.get("responseStatus", "needsAction") if own else None,
    )


def _safe_event(item: dict[str, Any], start: datetime, end: datetime) -> CalendarEvent | None:
    """One odd event (bad date, missing id) must not hide every other event, so it is skipped."""
    try:
        return _to_event(item, start, end)
    except (KeyError, ValueError, TypeError):
        log.warning("google_calendar.event_skipped")
        return None


class GoogleCalendarClient(CalendarClientProtocol):
    """Google Calendar API client using google-api-python-client or fake fallback."""

    def __init__(self, service: Any = None, calendar_id: str = "primary") -> None:
        self.service = service
        self.calendar_id = calendar_id
        self._fake_fallback = FakeCalendarClient() if service is None else None

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        if self._fake_fallback is not None:
            return self._fake_fallback.list_events(start, end)

        try:
            time_min = start.isoformat()
            time_max = end.isoformat()
            res = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=250,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            return [e for e in (_safe_event(item, start, end) for item in res.get("items", [])) if e is not None]
        except Exception as e:
            log.warning("google_calendar.list_events_failed", error=type(e).__name__)
            return []

    def check_free_busy(self, start: datetime, end: datetime) -> list[TimeSlot]:
        if self._fake_fallback is not None:
            return self._fake_fallback.check_free_busy(start, end)

        try:
            body = {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": self.calendar_id}],
            }
            res = self.service.freebusy().query(body=body).execute()
            busy_list = res.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
            slots = []
            for b in busy_list:
                s = datetime.fromisoformat(b["start"])
                e = datetime.fromisoformat(b["end"])
                slots.append(TimeSlot(start_time=s, end_time=e))
            return slots
        except Exception as e:
            log.warning("google_calendar.freebusy_failed", error=str(e))
            return []

    def create_event(self, event: CalendarEventCreate) -> CalendarEvent:
        if self._fake_fallback is not None:
            return self._fake_fallback.create_event(event)

        try:
            body = {
                "summary": event.title,
                "description": event.description,
                "location": event.location,
                "start": {"dateTime": event.start_time.isoformat()},
                "end": {"dateTime": event.end_time.isoformat()},
                "attendees": [{"email": a.email, "displayName": a.display_name} for a in event.attendees if a.email],
            }
            created = self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
            return CalendarEvent(
                id=created.get("id"),
                title=created.get("summary", event.title),
                description=created.get("description", event.description),
                start_time=event.start_time,
                end_time=event.end_time,
                location=created.get("location", event.location),
                status=created.get("status", "confirmed"),
                html_link=created.get("htmlLink"),
                created_at=datetime.now(UTC),
                metadata=event.metadata,
            )
        except Exception as e:
            log.error("google_calendar.create_event_failed", error=str(e))
            raise

    def update_event(self, event_id: str, updates: dict[str, Any]) -> CalendarEvent:
        if self._fake_fallback is not None:
            return self._fake_fallback.update_event(event_id, updates)
        res = self.service.events().patch(calendarId=self.calendar_id, eventId=event_id, body=updates).execute()
        return CalendarEvent(
            id=res.get("id"),
            title=res.get("summary", ""),
            description=res.get("description"),
            start_time=updates.get("start_time", datetime.now(UTC)),
            end_time=updates.get("end_time", datetime.now(UTC)),
            location=res.get("location"),
            status=res.get("status", "confirmed"),
            html_link=res.get("htmlLink"),
        )

    def delete_event(self, event_id: str) -> bool:
        if self._fake_fallback is not None:
            return self._fake_fallback.delete_event(event_id)
        try:
            self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
            return True
        except Exception as e:
            log.warning("google_calendar.delete_failed", error=str(e))
            return False

    def list_pending_invites(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [
            e
            for e in self.list_events(start, end)
            if e.self_response_status == "needsAction" and e.organizer_email and e.status != "cancelled"
        ]

    def respond_to_invite(self, event_id: str, response: str) -> CalendarEvent | None:
        if self._fake_fallback is not None:
            return self._fake_fallback.respond_to_invite(event_id, response)
        try:
            return self._patch_own_rsvp(event_id, response)
        except HttpError as e:  # deleted or changed between the list and the click
            log.warning("google_calendar.rsvp_failed", status=getattr(e.resp, "status", None))
            return None

    def _patch_own_rsvp(self, event_id: str, response: str) -> CalendarEvent | None:
        item = self.service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
        attendees = item.get("attendees", [])
        own = next((a for a in attendees if a.get("self")), None)
        if own is None or item.get("status") == "cancelled":
            return None
        own["responseStatus"] = response
        # `all`: the organiser is told the answer; that notice is the point of an RSVP (docs/standards/security.md).
        patched = (
            self.service.events()
            .patch(calendarId=self.calendar_id, eventId=event_id, body={"attendees": attendees}, sendUpdates="all")
            .execute()
        )
        now = datetime.now(UTC)
        return _to_event(patched, now, now)

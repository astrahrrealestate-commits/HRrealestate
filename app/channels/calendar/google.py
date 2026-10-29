"""Production Google Calendar API adapter with automatic fallback to FakeCalendarClient."""

from datetime import UTC, datetime
from typing import Any

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
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = res.get("items", [])
            events = []
            for item in items:
                start_raw = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
                end_raw = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
                st = datetime.fromisoformat(start_raw) if start_raw else start
                et = datetime.fromisoformat(end_raw) if end_raw else end
                events.append(
                    CalendarEvent(
                        id=item.get("id"),
                        title=item.get("summary", "Untitled"),
                        description=item.get("description"),
                        start_time=st,
                        end_time=et,
                        location=item.get("location"),
                        status=item.get("status", "confirmed"),
                        html_link=item.get("htmlLink"),
                    )
                )
            return events
        except Exception as e:
            log.warning("google_calendar.list_events_failed", error=str(e))
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


"""Calendar Agent: extraction, conflict checking, and appointment proposal generation."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    TimeSlot,
)
from app.core.errors import EstateOSError
from app.core.localtime import AMSTERDAM


@dataclass
class ExtractedTimeWindow:
    start_time: datetime
    end_time: datetime
    raw_expression: str
    confidence: float


@dataclass
class CalendarProposal:
    title: str
    start_time: datetime
    end_time: datetime
    location: str
    contractor_name: str | None = None
    lockbox_code: str | None = None
    attendees: list[CalendarAttendee] = field(default_factory=list)
    has_conflict: bool = False
    conflict_reason: str | None = None
    alternative_slot: TimeSlot | None = None
    notes: str = ""
    requires_lockbox: bool = False


DUTCH_DAYS = {
    "maandag": 0,
    "dinsdag": 1,
    "woensdag": 2,
    "donderdag": 3,
    "vrijdag": 4,
    "zaterdag": 5,
    "zondag": 6,
}

ENGLISH_DAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


class TimeNotStatedError(EstateOSError):
    """The message names no day and time we can read. We never invent a slot; the owner is asked instead."""


def _stated_day_offset(t: str, ref: datetime) -> int | None:
    """Days from `ref` to the day the text names (morgen, vandaag, a weekday), None when it names none."""
    if "morgen" in t or "tomorrow" in t:
        return 1
    if "vandaag" in t or "today" in t:
        return 0
    for day_name, day_idx in {**ENGLISH_DAYS, **DUTCH_DAYS}.items():
        if day_name in t:
            diff = (day_idx - ref.weekday()) % 7
            return 7 if diff == 0 and "next" in t else diff
    return None


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=AMSTERDAM)


def _clock_hour(m: re.Match[str]) -> tuple[int, int]:
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    meridiem = m.group(3).lower() if (m.lastindex or 0) >= 3 and m.group(3) else None
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute


def extract_time_window(text: str, reference_date: datetime | None = None) -> ExtractedTimeWindow:
    """The day and time window the message states, in Dutch time. Raises `TimeNotStatedError` when the text names no
    day or no time of day: a meeting time is never guessed."""
    ref = (reference_date or datetime.now(AMSTERDAM)).astimezone(AMSTERDAM)
    t = text.lower()
    offset = _stated_day_offset(t, ref)
    if offset is None:
        raise TimeNotStatedError("the message names no day")
    day = ref.date() + timedelta(days=offset)

    range_match = re.search(r"(\d{1,2}):(\d{2})\s*(?:en|-|tot|to|and)\s*(\d{1,2}):(\d{2})", t)
    if range_match:
        sh, sm, eh, em = map(int, range_match.groups())
        return ExtractedTimeWindow(_at(day, sh, sm), _at(day, eh, em), range_match.group(0), confidence=0.95)

    for pat in (
        r"(?:om|at)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        r"(\d{1,2}):(\d{2})",
    ):
        m = re.search(pat, t)
        if m:
            hour, minute = _clock_hour(m)
            start = _at(day, hour, minute)
            return ExtractedTimeWindow(start, start + timedelta(hours=1), f"{start:%A %H:%M}", confidence=0.90)

    if "ochtend" in t or "morning" in t:
        return ExtractedTimeWindow(_at(day, 10), _at(day, 11, 30), "morning", confidence=0.80)
    if "middag" in t or "afternoon" in t:
        return ExtractedTimeWindow(_at(day, 14), _at(day, 15, 30), "afternoon", confidence=0.80)
    raise TimeNotStatedError("the message names no time of day")


def detect_lockbox_need(text: str) -> bool:
    """Detect if tenant is unavailable / away and lockbox code should be dispatched."""
    t = text.lower()
    patterns = [
        r"sleutelkluis",
        r"lockbox",
        r"niet thuis",
        r"not home",
        r"op kantoor",
        r"at work",
        r"away",
        r"sleutel achterlaten",
        r"leave key",
    ]
    return any(re.search(p, t) for p in patterns)


def propose_calendar_event(
    message_text: str,
    property_address: str,
    calendar_client: CalendarClientProtocol,
    contractor_name: str | None = None,
    contractor_email: str | None = None,
    tenant_email: str | None = None,
    lockbox_pin: str | None = None,
    reference_date: datetime | None = None,
) -> CalendarProposal:
    """Analyze message, extract timing, check Google Calendar busy slots, and propose 1-click event."""
    tw = extract_time_window(message_text, reference_date=reference_date)
    needs_lockbox = detect_lockbox_need(message_text)

    # Check for busy conflicts on calendar
    busy_slots = calendar_client.check_free_busy(tw.start_time, tw.end_time)
    has_conflict = len(busy_slots) > 0

    alternative_slot: TimeSlot | None = None
    conflict_reason: str | None = None

    if has_conflict:
        first = busy_slots[0]
        conflict_reason = (
            f"Slot collides with existing booking from {first.start_time.astimezone(AMSTERDAM):%H:%M} "
            f"to {first.end_time.astimezone(AMSTERDAM):%H:%M}"
        )
        # Offer the slot right after the collision only when the calendar confirms it is free; never invent one.
        alt_start = first.end_time + timedelta(minutes=30)
        alt_end = alt_start + timedelta(hours=1)
        if not calendar_client.check_free_busy(alt_start, alt_end):
            alternative_slot = TimeSlot(start_time=alt_start, end_time=alt_end)

    # Compile attendee list
    attendees: list[CalendarAttendee] = []
    if contractor_email:
        attendees.append(CalendarAttendee(email=contractor_email, display_name=contractor_name))
    if tenant_email:
        attendees.append(CalendarAttendee(email=tenant_email, display_name="Tenant"))

    title = f"Maintenance Inspection · {property_address}"
    if contractor_name:
        title = f"{contractor_name.split()[0]} Visit · {property_address}"

    notes_parts = []
    if needs_lockbox:
        if lockbox_pin:
            notes_parts.append(f"Tenant is away. Lockbox code: #{lockbox_pin}.")
        else:
            notes_parts.append("Tenant is away. Direct access coordination needed.")

    return CalendarProposal(
        title=title,
        start_time=tw.start_time,
        end_time=tw.end_time,
        location=property_address,
        contractor_name=contractor_name,
        lockbox_code=lockbox_pin if needs_lockbox else None,
        attendees=attendees,
        has_conflict=has_conflict,
        conflict_reason=conflict_reason,
        alternative_slot=alternative_slot,
        notes=" ".join(notes_parts),
        requires_lockbox=needs_lockbox,
    )

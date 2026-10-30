"""Calendar Agent: extraction, conflict checking, and appointment proposal generation."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.channels.calendar.ports import (
    CalendarAttendee,
    CalendarClientProtocol,
    CalendarEventCreate,
    TimeSlot,
)


@dataclass
class ExtractedTimeWindow:
    start_time: datetime
    end_time: datetime
    raw_expression: str
    confidence: float
    is_default_fallback: bool = False


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
    clarification_needed: bool = False


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


def extract_time_window(text: str, reference_date: datetime | None = None) -> ExtractedTimeWindow:
    """Extract requested date & time window from message in English or Dutch."""
    ref = reference_date or datetime.now(UTC)
    t = text.lower()

    # 1. Range like '11:30 en 12:30' or '11:30 - 12:30' or '11:30 to 12:30'
    range_match = re.search(r"(\d{1,2}):(\d{2})\s*(?:en|-|tot|to|and)\s*(\d{1,2}):(\d{2})", t)
    if range_match:
        sh, sm, eh, em = map(int, range_match.groups())
        target_day = ref.date()
        if "morgen" in t or "tomorrow" in t:
            target_day += timedelta(days=1)
        start = datetime(target_day.year, target_day.month, target_day.day, sh, sm, tzinfo=UTC)
        end = datetime(target_day.year, target_day.month, target_day.day, eh, em, tzinfo=UTC)
        return ExtractedTimeWindow(
            start_time=start,
            end_time=end,
            raw_expression=range_match.group(0),
            confidence=0.95,
        )

    # 2. Specific hour like '15:00', '3 pm', '14:30', '9 am'
    hour_match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    target_hour = None
    target_min = 0

    # Look for day of week (Dutch or English)
    day_offset = None
    for day_name, day_idx in {**ENGLISH_DAYS, **DUTCH_DAYS}.items():
        if day_name in t:
            current_day_idx = ref.weekday()
            diff = (day_idx - current_day_idx) % 7
            if diff == 0 and "next" in t:
                diff = 7
            day_offset = diff
            break

    if "morgen" in t or "tomorrow" in t:
        day_offset = 1
    elif "vandaag" in t or "today" in t:
        day_offset = 0

    time_patterns = [
        r"(?:om|at)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
        r"(\d{1,2}):(\d{2})",
    ]

    for pat in time_patterns:
        m = re.search(pat, t)
        if m:
            h = int(m.group(1))
            m_min = int(m.group(2)) if m.group(2) else 0
            meridiem = m.group(3).lower() if m.lastindex >= 3 and m.group(3) else None
            if meridiem == "pm" and h < 12:
                h += 12
            elif meridiem == "am" and h == 12:
                h = 0
            target_hour = h
            target_min = m_min
            break

    if target_hour is not None:
        target_day = ref.date() + timedelta(days=day_offset if day_offset is not None else 0)
        start = datetime(target_day.year, target_day.month, target_day.day, target_hour, target_min, tzinfo=UTC)
        end = start + timedelta(hours=1)
        return ExtractedTimeWindow(
            start_time=start,
            end_time=end,
            raw_expression=f"{start.strftime('%A %H:%M')}",
            confidence=0.90,
        )

    # 3. Morning / Afternoon keywords
    if "ochtend" in t or "morning" in t:
        target_day = ref.date() + timedelta(days=day_offset if day_offset is not None else 1)
        start = datetime(target_day.year, target_day.month, target_day.day, 10, 0, tzinfo=UTC)
        end = datetime(target_day.year, target_day.month, target_day.day, 11, 30, tzinfo=UTC)
        return ExtractedTimeWindow(start, end, "morning", confidence=0.80)

    if "middag" in t or "afternoon" in t:
        target_day = ref.date() + timedelta(days=day_offset if day_offset is not None else 1)
        start = datetime(target_day.year, target_day.month, target_day.day, 14, 0, tzinfo=UTC)
        end = datetime(target_day.year, target_day.month, target_day.day, 15, 30, tzinfo=UTC)
        return ExtractedTimeWindow(start, end, "afternoon", confidence=0.80)

    # 4. Fallback when no explicit time was found in the message
    fallback_day = ref.date() + timedelta(days=1)
    if fallback_day.weekday() >= 5:  # Weekend jump to Monday
        fallback_day += timedelta(days=(7 - fallback_day.weekday()))
    start = datetime(fallback_day.year, fallback_day.month, fallback_day.day, 10, 0, tzinfo=UTC)
    end = datetime(fallback_day.year, fallback_day.month, fallback_day.day, 11, 0, tzinfo=UTC)
    return ExtractedTimeWindow(
        start_time=start,
        end_time=end,
        raw_expression="next business morning (default)",
        confidence=0.50,
        is_default_fallback=True,
    )


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
    contractor_name: str | None = "Kevin van Dijk (Technician)",
    contractor_email: str | None = "kevin@chahalbouw.nl",
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
        conflict_reason = f"Slot collides with existing booking from {busy_slots[0].start_time.strftime('%H:%M')} to {busy_slots[0].end_time.strftime('%H:%M')}"
        # Search next available slot 1 hour after collision
        alt_start = busy_slots[0].end_time + timedelta(minutes=30)
        alt_end = alt_start + timedelta(hours=1)
        # Check if that slot is free
        secondary_busy = calendar_client.check_free_busy(alt_start, alt_end)
        if not secondary_busy:
            alternative_slot = TimeSlot(start_time=alt_start, end_time=alt_end)
        else:
            # Morning fallback
            alt_day = alt_start.date() + timedelta(days=1)
            alt_start = datetime(alt_day.year, alt_day.month, alt_day.day, 10, 0, tzinfo=UTC)
            alt_end = alt_start + timedelta(hours=1)
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
    if tw.is_default_fallback:
        notes_parts.append("Proposed slot based on standard availability window (needs tenant confirmation).")

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
        clarification_needed=tw.is_default_fallback,
    )


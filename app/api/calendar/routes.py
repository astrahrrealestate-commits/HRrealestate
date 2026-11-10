"""Calendar & Appointment Management REST API Routes.

Exposes endpoints for listing events, proposing appointment slots with conflict detection,
and executing Harjot's 1-click confirmation to sync events to Google Calendar.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import decide_limit
from app.channels.calendar import CalendarAttendee, CalendarEventCreate, get_calendar_client
from app.core.logging import get_logger
from app.db.enums import CaseEventKind
from app.db.models import Case, CaseEvent, Unit
from app.db.models.calendar import CalendarEventRow
from app.llm.agents.calendar import propose_calendar_event

router = APIRouter(
    prefix="/api/calendar",
    tags=["calendar"],
    dependencies=[Depends(require_section("maintenance", also=("dashboard", "inbox")))],
)
log = get_logger(__name__)


class CalendarEventResponse(BaseModel):
    id: str
    caseId: str | None = None
    unitId: str | None = None
    title: str
    description: str | None = None
    startTime: str
    endTime: str
    status: str
    eventType: str
    externalEventId: str | None = None
    location: str | None = None
    attendees: list[dict[str, Any]] = Field(default_factory=list)
    lockboxCode: str | None = None
    createdAt: str
    confirmedAt: str | None = None
    htmlLink: str | None = None


class CreateCalendarEventRequest(BaseModel):
    title: str
    startTime: str
    endTime: str
    caseId: str | None = None
    unitId: str | None = None
    description: str | None = None
    location: str | None = None
    eventType: str = "contractor_repair"
    lockboxCode: str | None = None
    contractorName: str | None = None
    contractorEmail: str | None = None


class ProposeSlotRequest(BaseModel):
    messageText: str
    propertyAddress: str
    contractorName: str | None = "Kevin van Dijk (Technician)"
    contractorEmail: str | None = "kevin@chahalbouw.nl"
    lockboxCode: str | None = None
    caseId: str | None = None


def _event_response(r: CalendarEventRow, html_link: str | None = None) -> CalendarEventResponse:
    return CalendarEventResponse(
        id=str(r.id),
        caseId=str(r.case_id) if r.case_id else None,
        unitId=str(r.unit_id) if r.unit_id else None,
        title=r.title,
        description=r.description,
        startTime=r.start_time.isoformat(),
        endTime=r.end_time.isoformat(),
        status=r.status,
        eventType=r.event_type,
        externalEventId=r.external_event_id,
        location=r.location,
        attendees=r.attendees or [],
        lockboxCode=r.lockbox_code,
        createdAt=r.created_at.isoformat() if r.created_at else datetime.now(UTC).isoformat(),
        confirmedAt=r.confirmed_at.isoformat() if r.confirmed_at else None,
        htmlLink=html_link
        or (f"https://calendar.google.com/calendar/event?eid={r.external_event_id}" if r.external_event_id else None),
    )


@router.get("/events", response_model=dict[str, Any])
def list_calendar_events(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    status: str | None = Query(default=None, description="proposed, confirmed, cancelled"),
    case_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """List the signed-in company's calendar events."""
    with Session(engine) as session:
        query = select(CalendarEventRow).where(CalendarEventRow.company_id == principal.company_id)
        if status:
            query = query.where(CalendarEventRow.status == status)
        if case_id:
            try:
                c_uuid = UUID(case_id.replace("case-", ""))
                query = query.where(CalendarEventRow.case_id == c_uuid)
            except ValueError:
                pass

        query = query.order_by(CalendarEventRow.start_time.asc())
        rows = session.scalars(query).all()

        events_out = [_event_response(r) for r in rows]

    return {"events": events_out, "total": len(events_out)}


@router.post("/propose", response_model=dict[str, Any])
def propose_slot(
    req: ProposeSlotRequest,
) -> dict[str, Any]:
    """Parse text, detect timing & lockbox, check Google Calendar busy slots, and propose an appointment."""
    client = get_calendar_client()
    proposal = propose_calendar_event(
        message_text=req.messageText,
        property_address=req.propertyAddress,
        calendar_client=client,
        contractor_name=req.contractorName,
        contractor_email=req.contractorEmail,
        lockbox_pin=req.lockboxCode,
    )

    return {
        "title": proposal.title,
        "startTime": proposal.start_time.isoformat(),
        "endTime": proposal.end_time.isoformat(),
        "location": proposal.location,
        "contractorName": proposal.contractor_name,
        "lockboxCode": proposal.lockbox_code,
        "hasConflict": proposal.has_conflict,
        "conflictReason": proposal.conflict_reason,
        "alternativeSlot": {
            "startTime": proposal.alternative_slot.start_time.isoformat(),
            "endTime": proposal.alternative_slot.end_time.isoformat(),
        }
        if proposal.alternative_slot
        else None,
        "notes": proposal.notes,
        "requiresLockbox": proposal.requires_lockbox,
        "clarificationNeeded": proposal.clarification_needed,
    }


def _parse_id(value: str, prefix: str) -> UUID:
    try:
        return UUID(value.removeprefix(prefix))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid id {value!r}") from None


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"invalid time {value!r}"
        ) from None


@router.post("/events", response_model=CalendarEventResponse)
def create_event(
    req: CreateCalendarEventRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> CalendarEventResponse:
    """Create a proposed or scheduled calendar event for the signed-in company; the case and unit it names must be
    that company's own."""
    st = _parse_time(req.startTime)
    et = _parse_time(req.endTime)
    case_uuid = _parse_id(req.caseId, "case-") if req.caseId else None
    unit_uuid = _parse_id(req.unitId, "unit-") if req.unitId else None
    comp_id = principal.company_id

    with Session(engine) as session, session.begin():
        if (
            case_uuid is not None
            and session.scalar(select(Case.id).where(Case.id == case_uuid, Case.company_id == comp_id)) is None
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
        if (
            unit_uuid is not None
            and session.scalar(select(Unit.id).where(Unit.id == unit_uuid, Unit.company_id == comp_id)) is None
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unit not found")

        attendees_data = []
        if req.contractorEmail:
            attendees_data.append({"email": req.contractorEmail, "displayName": req.contractorName or "Contractor"})

        row = CalendarEventRow(
            company_id=comp_id,
            case_id=case_uuid,
            unit_id=unit_uuid,
            title=req.title,
            description=req.description,
            start_time=st,
            end_time=et,
            location=req.location,
            status="proposed",
            event_type=req.eventType,
            attendees=attendees_data,
            lockbox_code=req.lockboxCode,
        )
        session.add(row)
        session.flush()

        res = _event_response(row)
    return res


@router.post("/events/{event_id}/approve", response_model=CalendarEventResponse, dependencies=[Depends(decide_limit)])
def approve_calendar_event(
    event_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> CalendarEventResponse:
    """Execute Harjot's 1-click approval: confirms event, pushes to Google Calendar, and updates case summary.
    Only the signed-in company's events; an event that is already confirmed is returned as it is (one Google event per
    approval, however often the button is clicked) and a cancelled one is refused."""
    target_uuid = _parse_id(event_id.removeprefix("evt-").removeprefix("cal-"), "")

    with Session(engine) as session, session.begin():
        evt = session.scalars(
            select(CalendarEventRow).where(
                CalendarEventRow.id == target_uuid, CalendarEventRow.company_id == principal.company_id
            )
        ).first()
        if not evt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Calendar event {event_id} not found")
        if evt.status == "cancelled":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="event is cancelled")
        if evt.status == "confirmed":
            return _event_response(evt)
        client = get_calendar_client()

        # 1. Push to Google Calendar via client protocol
        attendees = [
            CalendarAttendee(email=a.get("email", ""), display_name=a.get("displayName"))
            for a in (evt.attendees or [])
            if isinstance(a, dict) and a.get("email")
        ]
        gcal_create = CalendarEventCreate(
            title=evt.title,
            start_time=evt.start_time,
            end_time=evt.end_time,
            description=evt.description,
            location=evt.location,
            attendees=attendees,
            metadata={"case_id": str(evt.case_id)} if evt.case_id else {},
        )
        created_gcal = client.create_event(gcal_create)

        # 2. Update DB status and external event ID
        evt.status = "confirmed"
        evt.confirmed_at = datetime.now(UTC)
        evt.external_event_id = created_gcal.id

        # 3. If tied to a case, update case summary and emit append-only CaseEvent
        if evt.case_id:
            case = session.get(Case, evt.case_id)
            if case:
                sched_stamp = evt.start_time.strftime("%A %b %d at %H:%M")
                note_text = f"Visit scheduled on Google Calendar for {sched_stamp} ({evt.title})."
                existing_sum = (case.summary or "").strip()
                if "Visit scheduled on Google Calendar" not in existing_sum:
                    case.summary = (
                        f"{existing_sum}\n\n[Calendar Scheduled: {note_text}]"
                        if existing_sum
                        else f"[Calendar Scheduled: {note_text}]"
                    )
                    case.summary_version = (case.summary_version or 0) + 1

                session.add(
                    CaseEvent(
                        company_id=case.company_id,
                        case_id=case.id,
                        kind=CaseEventKind.note,
                        note=(
                            f"Owner 1-click confirmed appointment: {evt.title} ({sched_stamp}). "
                            f"Google Event ID: {created_gcal.id}."
                        ),
                        actor="owner",
                    )
                )

        return _event_response(
            evt, created_gcal.html_link or f"https://calendar.google.com/calendar/event?eid={created_gcal.id}"
        )

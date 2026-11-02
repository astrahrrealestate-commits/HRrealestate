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
from app.channels.calendar import CalendarAttendee, CalendarEventCreate, get_calendar_client
from app.core.logging import get_logger
from app.db.enums import CaseEventKind
from app.db.models import Case, CaseEvent, Company
from app.db.models.calendar import CalendarEventRow
from app.llm.agents.calendar import propose_calendar_event

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
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


@router.get("/events", response_model=dict[str, Any])
def list_calendar_events(
    engine: Annotated[Engine, Depends(get_engine)],
    status: str | None = Query(default=None, description="proposed, confirmed, cancelled"),
    case_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """List calendar events from the database."""
    with Session(engine) as session:
        query = select(CalendarEventRow)
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

        events_out = []
        for r in rows:
            events_out.append(
                CalendarEventResponse(
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
                    htmlLink=f"https://calendar.google.com/calendar/event?eid={r.external_event_id}"
                    if r.external_event_id
                    else None,
                )
            )

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


@router.post("/events", response_model=CalendarEventResponse)
def create_event(
    req: CreateCalendarEventRequest,
    engine: Annotated[Engine, Depends(get_engine)],
) -> CalendarEventResponse:
    """Create a proposed or scheduled calendar event."""
    st = datetime.fromisoformat(req.startTime)
    et = datetime.fromisoformat(req.endTime)
    case_uuid = UUID(req.caseId.replace("case-", "")) if req.caseId else None
    unit_uuid = UUID(req.unitId.replace("unit-", "")) if req.unitId else None

    with Session(engine) as session, session.begin():
        company = session.scalars(select(Company)).first()
        comp_id = company.id if company else UUID("00000000-0000-0000-0000-000000000001")

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

        res = CalendarEventResponse(
            id=str(row.id),
            caseId=str(row.case_id) if row.case_id else None,
            unitId=str(row.unit_id) if row.unit_id else None,
            title=row.title,
            description=row.description,
            startTime=row.start_time.isoformat(),
            endTime=row.end_time.isoformat(),
            status=row.status,
            eventType=row.event_type,
            location=row.location,
            attendees=row.attendees or [],
            lockboxCode=row.lockbox_code,
            createdAt=row.created_at.isoformat(),
        )
    return res


@router.post("/events/{event_id}/approve", response_model=CalendarEventResponse)
def approve_calendar_event(
    event_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> CalendarEventResponse:
    """Execute Harjot's 1-click approval: confirms event, pushes to Google Calendar, and updates case summary."""
    client = get_calendar_client()
    clean_id = event_id.replace("evt-", "").replace("cal-", "")
    target_uuid = UUID(clean_id)

    with Session(engine) as session, session.begin():
        evt = session.get(CalendarEventRow, target_uuid)
        if not evt:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Calendar event {event_id} not found")

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

        return CalendarEventResponse(
            id=str(evt.id),
            caseId=str(evt.case_id) if evt.case_id else None,
            unitId=str(evt.unit_id) if evt.unit_id else None,
            title=evt.title,
            description=evt.description,
            startTime=evt.start_time.isoformat(),
            endTime=evt.end_time.isoformat(),
            status=evt.status,
            eventType=evt.event_type,
            externalEventId=evt.external_event_id,
            location=evt.location,
            attendees=evt.attendees or [],
            lockboxCode=evt.lockbox_code,
            createdAt=evt.created_at.isoformat() if evt.created_at else datetime.now(UTC).isoformat(),
            confirmedAt=evt.confirmed_at.isoformat() if evt.confirmed_at else None,
            htmlLink=created_gcal.html_link or f"https://calendar.google.com/calendar/event?eid={created_gcal.id}",
        )

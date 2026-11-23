"""Incoming Google Calendar invites sent straight to the owner (not proposed by EstateOS).

Only property-related invites surface: the organiser is a known person (their email is one of the company's current
channel identities) or the event's location is one of the company's unit addresses. Everything else (friends, doctors)
is ignored. Accept / decline / tentative is one owner click and patches the owner's own RSVP on Google; it sends
no tenant or contractor message.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import decide_limit
from app.channels.calendar import CalendarEvent, CalendarUnavailableError, get_calendar_client
from app.contracts import Channel
from app.core.logging import get_logger
from app.db.models import ChannelIdentity, Person, Unit

router = APIRouter(
    prefix="/api/calendar",
    tags=["calendar"],
    dependencies=[Depends(require_section("maintenance", also=("inbox",), also_read=("dashboard",)))],
)
log = get_logger(__name__)

LOOKAHEAD = timedelta(days=60)
MIN_ADDRESS_CHARS = 8  # shorter "addresses" ("1", a street name) would match almost any location


@dataclass(frozen=True)
class KnownPerson:
    name: str
    kind: str
    trade: str | None


@dataclass(frozen=True)
class KnownUnit:
    id: UUID
    label: str
    address: str


class InvitePerson(BaseModel):
    name: str
    kind: str
    trade: str | None = None


class InviteUnit(BaseModel):
    id: str
    label: str


class IncomingInvite(BaseModel):
    id: str
    title: str
    startTime: str
    endTime: str
    location: str | None = None
    organizerEmail: str
    organizerName: str | None = None
    htmlLink: str | None = None
    matchedBy: Literal["organizer", "address"]
    person: InvitePerson | None = None
    unit: InviteUnit | None = None


class InviteResponseRequest(BaseModel):
    response: Literal["accepted", "declined", "tentative"]


def _address_in(address: str, location: str) -> bool:
    """The whole address is in the lower-cased location, on word boundaries, and long enough to be specific."""
    needle = address.strip().lower()
    return len(needle) >= MIN_ADDRESS_CHARS and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", location) is not None


def match_invite(event: CalendarEvent, people: dict[str, KnownPerson], units: list[KnownUnit]) -> IncomingInvite | None:
    """The invite as the dashboard shows it, or None when it is not about one of the company's properties or people.
    `people` is keyed by lower-cased email."""
    organizer = (event.organizer_email or "").strip().lower()
    if not organizer:
        return None
    person = people.get(organizer)
    where = (event.location or "").lower()
    unit = next((u for u in units if _address_in(u.address, where)), None) if where else None
    if person is None and unit is None:
        return None
    return IncomingInvite(
        id=event.id,
        title=event.title,
        startTime=event.start_time.isoformat(),
        endTime=event.end_time.isoformat(),
        location=event.location,
        organizerEmail=organizer,
        organizerName=event.organizer_name or (person.name if person else None),
        htmlLink=event.html_link,
        matchedBy="organizer" if person else "address",
        person=InvitePerson(name=person.name, kind=person.kind, trade=person.trade) if person else None,
        unit=InviteUnit(id=str(unit.id), label=unit.label) if unit else None,
    )


def _load_directory(session: Session, company_id: UUID) -> tuple[dict[str, KnownPerson], list[KnownUnit]]:
    rows = session.execute(
        select(ChannelIdentity.identity, Person.display_name, Person.kind, Person.trade)
        .join(Person, Person.id == ChannelIdentity.person_id)
        .where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == Channel.gmail,
            ChannelIdentity.valid_to.is_(None),
            Person.company_id == company_id,
            Person.valid_to.is_(None),
            func.strpos(ChannelIdentity.identity, "@") > 0,
        )
    ).all()
    people = {i.lower(): KnownPerson(name=n, kind=str(k), trade=t) for i, n, k, t in rows}
    unit_rows = session.execute(
        select(Unit.id, Unit.label, Unit.address).where(
            Unit.company_id == company_id, Unit.valid_to.is_(None), Unit.address.is_not(None)
        )
    ).all()
    return people, [KnownUnit(id=i, label=lbl, address=a) for i, lbl, a in unit_rows if a and a.strip()]


def _property_invites(engine: Engine, company_id: UUID) -> list[IncomingInvite]:
    now = datetime.now(UTC)
    try:
        events = get_calendar_client().list_pending_invites(now, now + LOOKAHEAD)
    except CalendarUnavailableError:
        return []  # not connected: no invites are known, none are invented
    if not events:
        return []
    with Session(engine) as session:
        people, units = _load_directory(session, company_id)
    matched = (match_invite(e, people, units) for e in events)
    return [m for m in matched if m is not None]


def _can_see_invites(principal: Principal) -> bool:
    """A Dashboard-only profile never sees who invited the owner (ADR 0012); it gets an empty list."""
    return principal.access.can("maintenance") or principal.access.can("inbox")


@router.get("/invites", response_model=dict[str, Any])
def list_incoming_invites(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, Any]:
    """Pending invites in the owner's Google Calendar that concern a known contact or one of the company's units."""
    invites = _property_invites(engine, principal.company_id) if _can_see_invites(principal) else []
    return {"invites": [i.model_dump() for i in invites], "total": len(invites)}


@router.post("/invites/{event_id}/respond", response_model=IncomingInvite, dependencies=[Depends(decide_limit)])
def respond_to_invite(
    event_id: str,
    req: InviteResponseRequest,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> IncomingInvite:
    """Set the owner's RSVP. Only an invite that is still a pending, property-related one for this company can be
    answered; any other event id is a 404, so the route cannot be used to touch arbitrary calendar entries."""
    if not _can_see_invites(principal):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    invite = next((i for i in _property_invites(engine, principal.company_id) if i.id == event_id), None)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invite not found")
    updated = get_calendar_client().respond_to_invite(event_id, req.response)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="invite is no longer open")
    log.info("calendar.invite_answered", response=req.response, matched_by=invite.matchedBy)
    return invite

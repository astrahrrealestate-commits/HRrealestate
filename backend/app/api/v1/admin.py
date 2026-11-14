"""Dashboard API: team profiles and which sections each may open (superadmin only, ADR 0012).

A profile is a whitelist entry (`allowed_users`): a name, the Google account that signs in, a role and, for a member,
the sections it can see. Changes apply on the person's next request; nothing is cached in their session.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Engine, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.access import require_admin
from app.api.v1.auth import Principal, email_fingerprint
from app.api.v1.sections import ADMIN_ROLES, SECTION_KEYS, SECTIONS
from app.contracts.message import normalise_identity
from app.core.logging import get_logger
from app.db.models import AllowedUser, OwnerAccount

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
log = get_logger(__name__)
Admin = Annotated[Principal, Depends(require_admin)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Role = Literal["superadmin", "member"]


class SectionOut(BaseModel):
    key: str
    label: str
    description: str


class ProfileOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    sections: list[str] = Field(description="Sections this profile can open (every section for a superadmin)")
    is_active: bool
    invited_by: str | None
    created_at: datetime


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, description="The Google account this person signs in with")
    role: Role = "member"
    sections: list[str] = []


class ProfilePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    sections: list[str] | None = None
    is_active: bool | None = None


def _profile(row: AllowedUser) -> ProfileOut:
    everything = row.role in ADMIN_ROLES or row.sections is None
    return ProfileOut(
        id=row.id,
        name=row.display_name,
        email=row.email,
        role=row.role,
        sections=[s.key for s in SECTIONS if everything or s.key in (row.sections or [])],
        is_active=row.is_active,
        invited_by=row.invited_by,
        created_at=row.created_at,
    )


def _checked_sections(sections: list[str]) -> list[str]:
    unknown = sorted(set(sections) - SECTION_KEYS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown sections: {', '.join(unknown)}")
    return [s.key for s in SECTIONS if s.key in sections]  # catalogue order, no duplicates


def _checked_email(raw: str) -> str:
    try:
        email = normalise_identity(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="enter a valid email address") from None
    if "@" not in email:
        raise HTTPException(status_code=422, detail="enter a valid email address")
    return email


def _member_sections(role: str, sections: list[str]) -> list[str] | None:
    """`None` (every section) for an admin role; a member must be granted at least one section."""
    if role in ADMIN_ROLES:
        return None
    granted = _checked_sections(sections)
    if not granted:
        raise HTTPException(status_code=422, detail="grant a member at least one section")
    return granted


def _row(session: Session, company_id: UUID, profile_id: UUID) -> AllowedUser:
    row = session.scalar(select(AllowedUser).where(AllowedUser.id == profile_id, AllowedUser.company_id == company_id))
    if row is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return row


@router.get("/sections", summary="Sections a profile can be granted")
def list_sections() -> list[SectionOut]:
    return [SectionOut(key=s.key, label=s.label, description=s.description) for s in SECTIONS]


@router.get("/profiles", summary="Team profiles")
def list_profiles(who: Admin, engine: Engine_) -> list[ProfileOut]:
    with Session(engine) as session:
        rows = session.scalars(
            select(AllowedUser).where(AllowedUser.company_id == who.company_id).order_by(AllowedUser.created_at)
        ).all()
        return [_profile(r) for r in rows]


def _ensure_own_profile(session: Session, who: Principal) -> None:
    """A company with no whitelist rows lets its owner in without one (`access_for`). The first profile ends that, so
    the owner gets a superadmin row of their own in the same transaction; otherwise adding a colleague signs the
    owner out."""
    mine = session.scalar(
        select(AllowedUser.id).where(
            AllowedUser.company_id == who.company_id, func.lower(AllowedUser.email) == who.email.lower()
        )
    )
    if mine is not None:
        return
    name = session.scalar(
        select(OwnerAccount.display_name).where(
            OwnerAccount.id == who.owner_id, OwnerAccount.company_id == who.company_id
        )
    )
    session.add(
        AllowedUser(
            company_id=who.company_id,
            email=who.email.lower(),
            display_name=name or who.email.split("@")[0].title(),
            role="superadmin",
            is_active=True,
            invited_by="system",
        )
    )
    session.flush()


@router.post("/profiles", status_code=201, summary="Create a profile")
def create_profile(body: ProfileIn, who: Admin, engine: Engine_) -> ProfileOut:
    email, sections = _checked_email(body.email), _member_sections(body.role, body.sections)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="a profile needs a name")
    try:
        with Session(engine) as session, session.begin():
            _ensure_own_profile(session, who)
            row = AllowedUser(
                company_id=who.company_id,
                email=email,
                display_name=name,
                role=body.role,
                sections=sections,
                is_active=True,
                invited_by=who.email,
            )
            session.add(row)
            session.flush()
            out = _profile(row)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="that email already has a profile") from None
    log.info("admin.profile.created", email_hash=email_fingerprint(email), role=body.role, sections=sections)
    return out


def _locked_admins_and_target(session: Session, company_id: UUID, profile_id: UUID) -> list[AllowedUser]:
    """The company's admin rows and the target row, locked: two superadmins editing each other at the same moment
    queue up instead of both succeeding and leaving nobody in charge."""
    return list(
        session.scalars(
            select(AllowedUser)
            .where(
                AllowedUser.company_id == company_id,
                or_(AllowedUser.role.in_(ADMIN_ROLES), AllowedUser.id == profile_id),
            )
            .order_by(AllowedUser.id)
            .with_for_update()
        )
    )


def _check_edit_allowed(
    who: Principal, rows: list[AllowedUser], row: AllowedUser, *, stays_admin: bool, stays_active: bool
) -> None:
    mine = next((r for r in rows if r.email.lower() == who.email.lower()), None)
    if mine is not None and not (mine.is_active and mine.role in ADMIN_ROLES):
        raise HTTPException(status_code=403, detail="only a superadmin can manage profiles")  # changed mid-request
    actor_role = mine.role if mine is not None else who.access.role
    if row.role == "owner" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="only the owner can change the owner's profile")
    is_admin = row.role in ADMIN_ROLES
    if row.email.lower() == who.email.lower() and (not stays_active or (is_admin and not stays_admin)):
        raise HTTPException(status_code=409, detail="you cannot switch off or demote your own profile")
    others = [r for r in rows if r.id != row.id and r.is_active and r.role in ADMIN_ROLES]
    if is_admin and row.is_active and not (stays_admin and stays_active) and not others:
        raise HTTPException(status_code=409, detail="keep at least one active superadmin")


@router.patch("/profiles/{profile_id}", summary="Edit a profile")
def edit_profile(profile_id: UUID, body: ProfilePatch, who: Admin, engine: Engine_) -> ProfileOut:
    with Session(engine) as session, session.begin():
        rows = _locked_admins_and_target(session, who.company_id, profile_id)
        row = next((r for r in rows if r.id == profile_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail="profile not found")
        email, role = row.email, body.role or row.role
        stays_admin = role in ADMIN_ROLES
        stays_active = row.is_active if body.is_active is None else body.is_active
        _check_edit_allowed(who, rows, row, stays_admin=stays_admin, stays_active=stays_active)
        if body.sections is not None and body.role is None and stays_admin:
            raise HTTPException(status_code=422, detail="a superadmin sees every section; change the role first")
        if body.name is not None:
            row.display_name = " ".join(body.name.split()) or row.display_name
        if body.role is not None or body.sections is not None:
            current = [] if row.sections is None else row.sections
            row.sections = _member_sections(role, current if body.sections is None else body.sections)
            row.role = role
        row.is_active = stays_active
        session.flush()
        out = _profile(row)
    log.info("admin.profile.edited", email_hash=email_fingerprint(email), role=out.role, active=out.is_active)
    return out

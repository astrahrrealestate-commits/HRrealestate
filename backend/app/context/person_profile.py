"""T3 Entity Memory: Person profiles for tenants and contractors (spec §6.2, Task C10).

Maintains rolling profiles, contact statistics, open/closed cases count, and communication preferences.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import CaseState
from app.core.ids import new_id
from app.db.models import Case, CaseLink, MessageRow, Person, PersonProfile


def get_or_create_profile(session: Session, company_id: UUID, person_id: UUID) -> PersonProfile:
    """Retrieve existing profile or initialize a new one for person_id."""
    profile = session.scalar(
        select(PersonProfile).where(
            PersonProfile.company_id == company_id,
            PersonProfile.person_id == person_id,
        )
    )
    if profile is not None:
        return profile

    profile = PersonProfile(
        id=new_id(),
        company_id=company_id,
        person_id=person_id,
        language="nl",
        preferred_channel="whatsapp",
        summary="",
        open_cases=0,
        closed_cases=0,
        profile_version=1,
    )
    session.add(profile)
    session.flush()
    return profile


def mark_stale(session: Session, company_id: UUID, person_id: UUID, message_at: datetime) -> None:
    """Mark source_max_message_at when an inbound message is linked."""
    profile = get_or_create_profile(session, company_id, person_id)
    if profile.source_max_message_at is None or message_at > profile.source_max_message_at:
        profile.source_max_message_at = message_at  # an old mail (a reload) never moves the marker back
    if profile.last_contact_at is None or message_at > profile.last_contact_at:
        profile.last_contact_at = message_at


def person_profile_line(profile: PersonProfile | None) -> str | None:
    """A compact, escaped 1-line summary for prompt injection (link_check, proposer)."""
    if profile is None or not profile.summary.strip():
        return None
    summary_clean = " ".join(profile.summary.split())[:300]
    return f"Profile ({profile.language}, {profile.preferred_channel}): {summary_clean}"


def update_case_counts(session: Session, company_id: UUID, person_id: UUID) -> tuple[int, int]:
    """Compute open and closed case counts for a person."""
    open_count = (
        session.scalar(
            select(func.count(Case.id)).where(
                Case.company_id == company_id,
                Case.primary_person_id == person_id,
                Case.state != CaseState.closed,
            )
        )
        or 0
    )
    closed_count = (
        session.scalar(
            select(func.count(Case.id)).where(
                Case.company_id == company_id,
                Case.primary_person_id == person_id,
                Case.state == CaseState.closed,
            )
        )
        or 0
    )
    return open_count, closed_count


def refresh_profile_deterministic(session: Session, company_id: UUID, person_id: UUID) -> PersonProfile:
    """Refresh profile statistics and deterministic summary without external LLM call."""
    profile = get_or_create_profile(session, company_id, person_id)
    person = session.scalar(select(Person).where(Person.company_id == company_id, Person.id == person_id))

    open_c, closed_c = update_case_counts(session, company_id, person_id)
    profile.open_cases = open_c
    profile.closed_cases = closed_c

    # Find the most recent message channel if available
    latest_msg = session.execute(
        select(MessageRow.channel, MessageRow.created_at)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .join(Case, Case.id == CaseLink.case_id)
        .where(Case.company_id == company_id, Case.primary_person_id == person_id)
        .order_by(MessageRow.created_at.desc())
        .limit(1)
    ).first()

    if latest_msg:
        profile.preferred_channel = latest_msg[0].value if hasattr(latest_msg[0], "value") else str(latest_msg[0])
        profile.last_contact_at = latest_msg[1]

    name = person.display_name if person else "Contact"
    kind = person.kind.value if person and hasattr(person.kind, "value") else "person"
    profile.summary = f"{name} ({kind}): {open_c} open case(s), {closed_c} closed case(s)."
    profile.profile_version += 1
    return profile

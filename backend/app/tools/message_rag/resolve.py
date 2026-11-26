"""Who and what a message is about, for its chunk: person, case, unit, lease. Every lookup is inside the company."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Direction
from app.db.models import Case, CaseLink, ChannelIdentity, Lease, LeaseParty, MessageRow, Person, Unit


@dataclass(frozen=True)
class MessageFacts:
    person_id: UUID | None
    person_name: str | None
    case_id: UUID | None
    case_summary: str | None
    unit_id: UUID | None
    unit_address: str | None
    lease_id: UUID | None
    subject: str | None


def _recipient(session: Session, msg: MessageRow) -> UUID | None:
    """For an outbound message: the person of the thread, else of a known recipient address."""
    prior = None
    if msg.thread_ref is not None:
        prior = session.scalar(
            select(MessageRow.person_id)
            .where(
                MessageRow.company_id == msg.company_id,
                MessageRow.channel == msg.channel,
                MessageRow.thread_ref == msg.thread_ref,
                MessageRow.person_id.is_not(None),
            )
            .order_by(MessageRow.sent_at.desc())
            .limit(1)
        )
    if prior:
        return prior
    to_list = (msg.meta or {}).get("to") or []
    for recipient in [to_list] if isinstance(to_list, str) else to_list:
        person_id = session.scalar(
            select(ChannelIdentity.person_id).where(
                ChannelIdentity.company_id == msg.company_id,
                ChannelIdentity.identity == str(recipient).strip().lower(),
                ChannelIdentity.valid_to.is_(None),
            )
        )
        if person_id:
            return person_id
    return None


def _case(session: Session, msg: MessageRow) -> UUID | None:
    """The message's own case, else the one its thread is already linked to."""
    own = session.scalar(
        select(CaseLink.case_id).where(CaseLink.company_id == msg.company_id, CaseLink.message_id == msg.id)
    )
    if own is not None or msg.thread_ref is None:
        return own
    return session.scalar(
        select(CaseLink.case_id)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.company_id == msg.company_id,
            MessageRow.company_id == msg.company_id,
            MessageRow.channel == msg.channel,
            MessageRow.thread_ref == msg.thread_ref,
        )
        .order_by(MessageRow.sent_at.desc(), CaseLink.id.desc())
        .limit(1)
    )


def _unit_and_lease(
    session: Session, company_id: UUID, person_id: UUID | None, case: Case | None
) -> tuple[UUID | None, UUID | None]:
    if case is not None and case.unit_id:
        lease_id = session.scalar(
            select(Lease.id)
            .where(Lease.company_id == company_id, Lease.unit_id == case.unit_id)
            .order_by(Lease.valid_from.desc())
            .limit(1)
        )
        return case.unit_id, lease_id
    if person_id is None:
        return None, None
    row = session.execute(
        select(Lease.unit_id, Lease.id)
        .join(LeaseParty, LeaseParty.lease_id == Lease.id)
        .where(
            LeaseParty.company_id == company_id,
            Lease.company_id == company_id,
            LeaseParty.person_id == person_id,
        )
        .order_by(Lease.valid_from.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def resolve_facts(session: Session, msg: MessageRow) -> MessageFacts:
    cid = msg.company_id
    person_id = msg.person_id
    if person_id is None and msg.direction is Direction.outbound:
        person_id = _recipient(session, msg)
    name = session.scalar(select(Person.display_name).where(Person.company_id == cid, Person.id == person_id))
    case_id = _case(session, msg)
    case = session.scalar(select(Case).where(Case.company_id == cid, Case.id == case_id))
    unit_id, lease_id = _unit_and_lease(session, cid, person_id, case)
    address = session.scalar(select(Unit.address).where(Unit.company_id == cid, Unit.id == unit_id))
    return MessageFacts(
        person_id=person_id,
        person_name=name,
        case_id=case_id,
        case_summary=case.summary if case else None,
        unit_id=unit_id,
        unit_address=address,
        lease_id=lease_id,
        subject=(msg.meta or {}).get("subject"),
    )

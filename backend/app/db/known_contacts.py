"""Which senders feed the AI case pipeline. WhatsApp is the owner's own chat app, so most numbers that write are not
tenant or property business: only a contact the directory really knows enters the case pipeline, everyone else stays in
Chats (ADR 0015). Decided from the DB, never from message text.

The directory creates an `other` person on first contact (`resolve_person`), so a person row alone does not make a
number known. It needs a real kind (tenant, contractor, owner), a BRIXX reference, a trade (utility, municipal), a place
on a lease, or a case the pipeline opened for them. A number whose conversation a case already contains also stays
known (a third party Harjot approved a message to, who answers). An ended person (`valid_to` set) is still known: a
tenant whose lease just ended may still write about the deposit.
"""

from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import Case, CaseLink, ChannelIdentity, LeaseParty, MessageRow, OwnerAccount, Person


def _person_is_known(session: Session, company_id: UUID, channel: Channel, identity: str) -> bool:
    on_lease = exists().where(LeaseParty.company_id == Person.company_id, LeaseParty.person_id == Person.id)
    has_case = exists().where(Case.company_id == Person.company_id, Case.primary_person_id == Person.id)
    known = or_(
        Person.kind != PersonKind.other,
        Person.brixx_ref.is_not(None),
        Person.trade.is_not(None),  # a utility or municipal contact added by hand
        on_lease,
        has_case,
    )
    return (
        session.scalar(
            select(Person.id)
            .join(ChannelIdentity, ChannelIdentity.person_id == Person.id)
            .where(
                Person.company_id == company_id,
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.channel == channel,
                ChannelIdentity.identity == identity,
                ChannelIdentity.valid_to.is_(None),
                known,
            )
            .limit(1)
        )
        is not None
    )


def _thread_is_in_a_case(session: Session, company_id: UUID, channel: Channel, identity: str) -> bool:
    return (
        session.scalar(
            select(CaseLink.id)
            .join(MessageRow, MessageRow.id == CaseLink.message_id)
            .where(
                CaseLink.company_id == company_id,
                MessageRow.company_id == company_id,
                MessageRow.channel == channel,
                MessageRow.thread_ref == identity,
            )
            .limit(1)
        )
        is not None
    )


def is_known_contact(session: Session, company_id: UUID, channel: Channel, identity: str) -> bool:
    return _person_is_known(session, company_id, channel, identity) or _thread_is_in_a_case(
        session, company_id, channel, identity
    )


def feeds_pipeline(session: Session, company_id: UUID, channel: Channel, identity: str) -> bool:
    """The owner's own number (his commands are routed by the owner handler) or a contact the directory knows."""
    owner = session.scalar(
        select(OwnerAccount.id).where(OwnerAccount.company_id == company_id, OwnerAccount.whatsapp_e164 == identity)
    )
    return owner is not None or is_known_contact(session, company_id, channel, identity)

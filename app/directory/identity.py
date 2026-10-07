"""Identity-first directory (spec phase-1 agents): a phone/email resolves to a person, created on first contact.

The BRIXX importer (M3, deferred) later fills units/leases and upgrades `kind`; nothing here assumes BRIXX data.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, MessageRow, Person

MAX_NAME = 200


def current_person(session: Session, company_id: UUID, channel: Channel, identity: str) -> UUID | None:
    return session.scalar(
        select(ChannelIdentity.person_id).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == channel,
            ChannelIdentity.identity == identity,
            ChannelIdentity.valid_to.is_(None),
        )
    )


def resolve_person(
    session: Session, company_id: UUID, channel: Channel, identity: str, display_name: str | None, *, today: date
) -> UUID:
    """The current person for a normalised identity; a new `other` person when none exists. Concurrency-safe: a racing
    insert loses on the partial unique index and re-reads the winner. Flushes; the caller commits."""
    existing = current_person(session, company_id, channel, identity)
    if existing is not None:
        return existing
    name = (display_name or "").strip()[:MAX_NAME] or identity[:MAX_NAME]
    try:
        with session.begin_nested():
            person = Person(company_id=company_id, kind=PersonKind.other, display_name=name, valid_from=today)
            session.add(person)
            session.flush()
            session.add(
                ChannelIdentity(
                    company_id=company_id, person_id=person.id, channel=channel, identity=identity, valid_from=today
                )
            )
            session.flush()
            return person.id
    except IntegrityError:
        winner = current_person(session, company_id, channel, identity)
        if winner is None:
            raise
        return winner


def resolve_message_sender(engine: Engine, message_id: UUID) -> UUID | None:
    """Attach the sender's person to an inbound message (created on first contact). Idempotent."""
    with Session(engine) as session, session.begin():
        msg = session.get(MessageRow, message_id)
        if msg is None:
            return None
        if msg.person_id is None:
            name = msg.meta.get("contact_name") or msg.meta.get("from_name")
            msg.person_id = resolve_person(
                session, msg.company_id, msg.channel, msg.sender_identity, name, today=msg.sent_at.date()
            )
        return msg.person_id

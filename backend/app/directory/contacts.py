"""Contacts the owner adds by hand: a person plus the email and WhatsApp identities their messages arrive from.

A person that mail or WhatsApp already created (kind `other`, no BRIXX reference) is classified in place instead of
duplicated, so a hand-added contractor and the sender of their earlier emails are one contact.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.contracts.message import normalise_identity
from app.core.errors import EstateOSError, NotFoundError
from app.db.enums import PersonKind
from app.db.models import ChannelIdentity, LeaseParty, Person

CATEGORIES = ("tenant", "contractor", "owner", "utility", "municipal", "other")
_KIND = {
    "tenant": PersonKind.tenant,
    "contractor": PersonKind.contractor,
    "owner": PersonKind.owner,
    "utility": PersonKind.other,
    "municipal": PersonKind.other,
    "other": PersonKind.other,
}
_FIXED_TRADE = {"utility": "utility", "municipal": "municipal"}
DEFAULT_REGION = "NL"
MAX_NAME = 200
MAX_TRADE = 100


class ContactConflictError(EstateOSError):
    """The email or phone already belongs to another contact (`existing_id`), or the contact is managed by BRIXX."""

    def __init__(self, message: str, existing_id: UUID | None = None) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class InvalidContactError(EstateOSError, ValueError):
    """The name, category, email or phone cannot be used."""


def category_of(kind: PersonKind, trade: str | None) -> str:
    """The category the dashboard shows for a stored person."""
    if kind is PersonKind.other and trade and trade.lower() in _FIXED_TRADE.values():
        return trade.lower()
    return kind.value


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())[:MAX_NAME]
    if not cleaned:
        raise InvalidContactError("a contact needs a name")
    return cleaned


def _trade(category: str, trade: str | None) -> str | None:
    if category not in CATEGORIES:
        raise InvalidContactError(f"unknown category: {category}")
    if category in _FIXED_TRADE:
        return _FIXED_TRADE[category]
    cleaned = " ".join((trade or "").split())[:MAX_TRADE]
    if category == "other":
        return cleaned or "other"  # a role-less "other" is still classified (no trade means "not classified yet")
    return cleaned or None


def _identity(channel: Channel, raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    try:
        identity = normalise_identity(raw, DEFAULT_REGION)
    except ValueError:
        raise InvalidContactError(
            "enter a valid email address" if channel is Channel.gmail else "enter a valid phone number"
        ) from None
    if (channel is Channel.gmail) != ("@" in identity):
        raise InvalidContactError(
            "that is not an email address" if channel is Channel.gmail else "that is not a phone number"
        )
    return identity


def _current_identity(session: Session, company_id: UUID, channel: Channel, identity: str) -> ChannelIdentity | None:
    return session.scalar(
        select(ChannelIdentity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.channel == channel,
            ChannelIdentity.identity == identity,
            ChannelIdentity.valid_to.is_(None),
        )
    )


def _person(session: Session, company_id: UUID, person_id: UUID) -> Person:
    person = session.scalar(select(Person).where(Person.id == person_id, Person.company_id == company_id))
    if person is None:
        raise NotFoundError("contact not found")
    return person


def _has_lease(session: Session, company_id: UUID, person_id: UUID) -> bool:
    return (
        session.scalar(
            select(LeaseParty.id).where(LeaseParty.company_id == company_id, LeaseParty.person_id == person_id).limit(1)
        )
        is not None
    )


def _managed_by_brixx(person: Person) -> ContactConflictError:
    return ContactConflictError(f"{person.display_name} is managed by BRIXX; change them there", person.id)


def _target(session: Session, company_id: UUID, found: list[ChannelIdentity]) -> Person | None:
    """The one person the given identities already belong to, if any. Several people, or a classified one: conflict."""
    owners = {f.person_id for f in found}
    if len(owners) > 1:
        raise ContactConflictError("that email and phone belong to two different contacts")
    if not owners:
        return None
    person = _person(session, company_id, next(iter(owners)))
    if person.brixx_ref is not None or person.kind is not PersonKind.other or person.trade:
        raise ContactConflictError(f"{person.display_name} is already a contact", person.id)
    return person


_CHANNEL_NOUN = {Channel.gmail: "email address", Channel.whatsapp: "phone number"}


def _attach_identities(
    session: Session, company_id: UUID, person: Person, identities: list[tuple[Channel, str]], today: date
) -> None:
    """Give the person the email/phone they were added with. One current identity per channel: a different one than
    the person already has is a conflict, never a second row."""
    current = {
        row.channel: row.identity
        for row in session.scalars(
            select(ChannelIdentity).where(
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.person_id == person.id,
                ChannelIdentity.valid_to.is_(None),
            )
        )
    }
    for channel, value in identities:
        if channel not in current:
            session.add(
                ChannelIdentity(
                    company_id=company_id, person_id=person.id, channel=channel, identity=value, valid_from=today
                )
            )
        elif current[channel] != value:
            noun = _CHANNEL_NOUN[channel]
            raise ContactConflictError(f"{person.display_name} already has a different {noun}", person.id)
    session.flush()


def create_contact(
    session: Session,
    company_id: UUID,
    *,
    name: str,
    category: str,
    trade: str | None,
    email: str | None,
    phone: str | None,
    today: date,
) -> Person:
    """A new contact, or the unclassified person mail/WhatsApp already created for this email or phone. Flushes; the
    caller commits."""
    clean_name, stored_trade = _clean_name(name), _trade(category, trade)
    identities = [
        (channel, value)
        for channel, value in (
            (Channel.gmail, _identity(Channel.gmail, email)),
            (Channel.whatsapp, _identity(Channel.whatsapp, phone)),
        )
        if value is not None
    ]
    found = [row for channel, value in identities if (row := _current_identity(session, company_id, channel, value))]
    try:
        with session.begin_nested():
            person = _target(session, company_id, found)
            if person is None:
                person = Person(company_id=company_id, kind=_KIND[category], display_name=clean_name, valid_from=today)
                session.add(person)
            person.display_name, person.kind, person.trade = clean_name, _KIND[category], stored_trade
            session.flush()
            _attach_identities(session, company_id, person, identities, today)
            return person
    except IntegrityError:
        raise ContactConflictError("that email or phone was just added to another contact") from None


def update_contact(
    session: Session, company_id: UUID, person_id: UUID, *, name: str | None, category: str | None, trade: str | None
) -> Person:
    """Rename or reclassify a contact (typically one created from a message). Flushes; the caller commits."""
    person = _person(session, company_id, person_id)
    if person.brixx_ref is not None:
        raise _managed_by_brixx(person)
    if name is not None:
        person.display_name = _clean_name(name)
    if category is not None:
        if _KIND[category] is not PersonKind.tenant and _has_lease(session, company_id, person.id):
            raise ContactConflictError(f"{person.display_name} has a lease; change that in BRIXX first", person.id)
        person.kind, person.trade = _KIND[category], _trade(category, trade)
    elif trade is not None:
        person.trade = _trade(category_of(person.kind, person.trade), trade)
    session.flush()
    return person

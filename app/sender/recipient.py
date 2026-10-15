"""Who a tenant-facing message may go to, derived from the DB only (invariant 6).

The recipient is the stored sender of the case's latest inbound message on the channel, and only if that identity is a
current identity of the case's primary person. Message text, action payloads and model output never name a recipient.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.contracts.message import normalise_identity
from app.db.models import Case, CaseLink, ChannelAccount, ChannelIdentity, MessageRow, OwnerAccount
from app.sender.errors import SendBlockedError
from app.sender.owner_window import WINDOW


def latest_inbound(session: Session, company_id: UUID, case_id: UUID, channel: Channel) -> MessageRow | None:
    return session.scalar(
        select(MessageRow)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == company_id,
            MessageRow.company_id == company_id,
            CaseLink.case_id == case_id,
            MessageRow.channel == channel,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )


def canonical(identity: str) -> str | None:
    """The comparable form of an identity (E.164 / lowercase email), or None when it is not a valid identity."""
    try:
        return normalise_identity(identity)
    except ValueError:
        return None


def _own_addresses(session: Session, company_id: UUID) -> set[str]:
    """Every address that belongs to the company itself: owner numbers/emails and its channel accounts."""
    raw = [
        *session.scalars(select(OwnerAccount.whatsapp_e164).where(OwnerAccount.company_id == company_id)),
        *session.scalars(
            select(OwnerAccount.email).where(OwnerAccount.company_id == company_id, OwnerAccount.email.is_not(None))
        ),
        *session.scalars(select(ChannelAccount.address).where(ChannelAccount.company_id == company_id)),
    ]
    return {c for value in raw if value and (c := canonical(value))}


def _current_identities(session: Session, company_id: UUID, person_id: UUID, channel: Channel) -> set[str]:
    stored = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id == person_id,
            ChannelIdentity.channel == channel,
            ChannelIdentity.valid_to.is_(None),
        )
    )
    return {c for value in stored if (c := canonical(value))}


def tenant_recipient(session: Session, company_id: UUID, case_id: UUID, channel: Channel) -> tuple[MessageRow, str]:
    """The latest inbound message of the case on `channel` and its sender, if that sender is the case contact."""
    case = session.scalar(select(Case).where(Case.id == case_id, Case.company_id == company_id))
    if case is None:
        raise SendBlockedError("case not found")
    if case.primary_person_id is None:
        raise SendBlockedError("case has no contact person")
    msg = latest_inbound(session, company_id, case_id, channel)
    if msg is None:
        raise SendBlockedError(f"no inbound {channel.value} message on this case to reply to")
    identity = canonical(msg.sender_identity)
    if identity is None or identity in _own_addresses(session, company_id):
        raise SendBlockedError("recipient is not the case contact")
    if identity not in _current_identities(session, company_id, case.primary_person_id, channel):
        raise SendBlockedError("recipient is not the case contact")
    return msg, identity


def whatsapp_window_open(msg: MessageRow, now: datetime) -> bool:
    """Free-form WhatsApp is allowed within WINDOW of the inbound's receipt time; exactly at the boundary is closed."""
    return msg.created_at > now - WINDOW

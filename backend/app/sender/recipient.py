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
from app.core.wa_window import window_open
from app.db.models import Case, CaseLink, ChannelIdentity, MessageRow
from app.db.own_addresses import own_addresses
from app.sender.errors import SendBlockedError

CANDIDATES = 50
TENANT_CHANNELS = (Channel.whatsapp, Channel.gmail)


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
            MessageRow.meta["owner_authored"].astext.is_distinct_from("true"),  # Harjot's own copy is no addressee
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


def _candidates(session: Session, company_id: UUID, case_id: UUID, channel: Channel) -> list[MessageRow]:
    """The newest inbound messages of the case on the channel, newest first (deterministic order)."""
    return list(
        session.scalars(
            select(MessageRow)
            .join(CaseLink, CaseLink.message_id == MessageRow.id)
            .where(
                CaseLink.company_id == company_id,
                MessageRow.company_id == company_id,
                CaseLink.case_id == case_id,
                MessageRow.channel == channel,
                MessageRow.direction == Direction.inbound,
            )
            .order_by(MessageRow.sent_at.desc(), MessageRow.created_at.desc(), MessageRow.id.desc())
            .limit(CANDIDATES)
        )
    )


def tenant_recipient(session: Session, company_id: UUID, case_id: UUID, channel: Channel) -> tuple[MessageRow, str]:
    """The newest inbound message on `channel` written by the case's primary contact, and that contact's identity.

    Messages from anyone else (roommate, forwarder, spoofed sender, the company itself) are skipped, never used.
    """
    if channel not in TENANT_CHANNELS:
        raise SendBlockedError(f"{channel.value} is not a tenant reply channel")
    case = session.scalar(select(Case).where(Case.id == case_id, Case.company_id == company_id))
    if case is None:
        raise SendBlockedError("case not found")
    if case.primary_person_id is None:
        raise SendBlockedError("case has no contact person")
    allowed = _current_identities(session, company_id, case.primary_person_id, channel)
    allowed -= own_addresses(session, company_id)
    for msg in _candidates(session, company_id, case_id, channel):
        identity = canonical(msg.sender_identity)
        if identity is not None and identity in allowed:
            return msg, identity
    raise SendBlockedError("no inbound message from the case contact on this channel")


def whatsapp_window_open(msg: MessageRow, now: datetime) -> bool:
    """Free-form WhatsApp is allowed within WINDOW of the inbound's receipt time; exactly at the boundary is closed."""
    received = min(msg.sent_at, msg.created_at)  # the older of the two clocks: the conservative anchor
    return window_open(received, now)

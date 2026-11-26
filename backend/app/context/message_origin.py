"""What a stored message's metadata says about its origin (M13): reloaded history, Harjot's own mail, quoted text."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.core.settings import get_settings
from app.db.models import AllowedUser, ChannelAccount, MessageRow, OwnerAccount


def owner_emails(session: Session, company_id: UUID) -> frozenset[str]:
    """Addresses Harjot's team mails from: owner account, whitelisted users, configured owner email."""
    emails = [
        *session.scalars(select(OwnerAccount.email).where(OwnerAccount.company_id == company_id)),
        *session.scalars(select(AllowedUser.email).where(AllowedUser.company_id == company_id)),
        get_settings().owner_email,
    ]
    return frozenset(e.strip().lower() for e in emails if e and e.strip())


def mailbox_addresses(session: Session, company_id: UUID) -> frozenset[str]:
    """Every mailbox the company has connected."""
    addresses = session.scalars(
        select(ChannelAccount.address).where(
            ChannelAccount.company_id == company_id, ChannelAccount.channel == Channel.gmail
        )
    )
    return frozenset(a.strip().lower() for a in addresses)


def is_history(msg: MessageRow) -> bool:
    """Reloaded old mail: read, linked and remembered, but never drafted or announced."""
    return (msg.meta or {}).get("history") is True


def is_owner_authored(msg: MessageRow) -> bool:
    """Inbound mail whose sender is one of Harjot's addresses: his own words copied into the mailbox. From can be
    forged, so this only stops a draft; nothing it says counts as an approval."""
    return (msg.meta or {}).get("owner_authored") is True


def full_text(msg: MessageRow) -> str:
    """The mail as received, quoted history included; `text` alone when ingestion stripped nothing."""
    stored = (msg.meta or {}).get("full_text")
    return stored if isinstance(stored, str) and stored.strip() else msg.text

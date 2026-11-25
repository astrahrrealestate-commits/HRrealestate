"""The company's own addresses: owner numbers and emails and its channel accounts. Never a tenant, never a recipient.

Lives below both the sender and the API (neither may import the other): the sender refuses to send to these, and the
chats composer must not offer a box for them.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.message import normalise_identity
from app.db.models import ChannelAccount, OwnerAccount


def _canonical(identity: str) -> str | None:
    try:
        return normalise_identity(identity)
    except ValueError:
        return None


def own_addresses(session: Session, company_id: UUID) -> set[str]:
    """Every address that belongs to the company itself: owner numbers/emails and its channel accounts."""
    raw = [
        *session.scalars(select(OwnerAccount.whatsapp_e164).where(OwnerAccount.company_id == company_id)),
        *session.scalars(
            select(OwnerAccount.email).where(OwnerAccount.company_id == company_id, OwnerAccount.email.is_not(None))
        ),
        *session.scalars(select(ChannelAccount.address).where(ChannelAccount.company_id == company_id)),
    ]
    return {c for value in raw if value and (c := _canonical(value))}

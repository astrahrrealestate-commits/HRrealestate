"""WhatsApp 24-hour customer-service window for the owner channel.

Free-form messages reach Harjot only within 24 h of his last message to us (23 h here, for margin). Outside it, owner
messages wait in `owner_outbox` and one approved template per closed window tells him that items are waiting.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.wa_window import WINDOW as WINDOW
from app.db.enums import OutboxStatus
from app.db.models import MessageRow, OwnerOutbox


def last_owner_message(session: Session, company_id: UUID, owner: str) -> datetime | None:
    """When we last *received* a message from the owner (receipt time, not the provider's claimed send time)."""
    return session.scalar(
        select(func.max(MessageRow.created_at)).where(
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.inbound,
            MessageRow.sender_identity == owner,
        )
    )


def window_open(last: datetime | None, now: datetime) -> bool:
    return last is not None and last > now - WINDOW


def nudge_key(company_id: UUID, last: datetime | None) -> str:
    """One template per closed window: keyed by the owner message that opened the window that has now expired."""
    return f"nudge:{company_id}:{last.isoformat() if last else 'never'}"


def enqueue(session: Session, company_id: UUID, key: str, payload: dict[str, Any]) -> None:
    session.execute(
        insert(OwnerOutbox)
        .values(company_id=company_id, idempotency_key=key, payload=payload)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


def queued(session: Session, company_id: UUID) -> list[OwnerOutbox]:
    return list(
        session.scalars(
            select(OwnerOutbox)
            .where(OwnerOutbox.company_id == company_id, OwnerOutbox.status == OutboxStatus.queued)
            .order_by(OwnerOutbox.created_at, OwnerOutbox.id)
        ).all()
    )

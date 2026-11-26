"""Messages around a message, and the timeline of a person, unit or case (no search)."""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import Session

from app.context.shown_sender import shown_sender_name
from app.contracts import Channel
from app.db.models import Case, CaseLink, MessageRow, Person
from app.db.models.ingestion import not_chat_only


def get_message_window(
    session: Session,
    company_id: UUID,
    message_id: UUID,
    before: int = 4,
    after: int = 4,
) -> list[dict[str, Any]]:
    """Retrieves chronological raw messages before and after a specific message in the same thread."""
    target = session.get(MessageRow, message_id)
    if target is None or target.company_id != company_id:
        return []

    thread_ref = target.thread_ref or target.provider_msg_id

    # Messages before (ordered desc then reversed)
    before_rows = list(
        session.scalars(
            select(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.channel == target.channel,
                MessageRow.thread_ref == thread_ref,
                not_chat_only(),
                MessageRow.sent_at < target.sent_at,
            )
            .order_by(MessageRow.sent_at.desc())
            .limit(before)
        ).all()
    )
    before_rows.reverse()

    # Messages after
    after_rows = list(
        session.scalars(
            select(MessageRow)
            .where(
                MessageRow.company_id == company_id,
                MessageRow.channel == target.channel,
                MessageRow.thread_ref == thread_ref,
                not_chat_only(),
                MessageRow.sent_at > target.sent_at,
            )
            .order_by(MessageRow.sent_at.asc())
            .limit(after)
        ).all()
    )

    combined = [*before_rows, target, *after_rows]
    out: list[dict[str, Any]] = []
    for m in combined:
        person_name = session.scalar(
            select(Person.display_name).where(Person.company_id == company_id, Person.id == m.person_id)
        )
        meta = m.meta or {}
        out.append(
            {
                "message_id": str(m.id),
                "sent_at": m.sent_at.isoformat(),
                "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction),
                "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
                "sender": shown_sender_name(m, person_name),
                "text": m.text,
                "subject": meta.get("subject"),
            }
        )
    return out


def _in_cases(company_id: UUID, case_id: UUID | None, unit_id: UUID | None) -> ColumnElement[bool]:
    """Linked messages, and for email the rest of their threads: only inbound mail is linked, Harjot's replies are not.
    A WhatsApp thread is everything a contact ever wrote, so there only the linked messages count."""
    linked = (
        select(CaseLink.message_id)
        .join(Case, Case.id == CaseLink.case_id)
        .where(CaseLink.company_id == company_id, Case.company_id == company_id)
    )
    if case_id is not None:
        linked = linked.where(Case.id == case_id)
    if unit_id is not None:
        linked = linked.where(Case.unit_id == unit_id)
    threads = select(MessageRow.thread_ref).where(
        MessageRow.company_id == company_id, MessageRow.channel == Channel.gmail, MessageRow.id.in_(linked)
    )
    return or_(MessageRow.id.in_(linked), and_(MessageRow.channel == Channel.gmail, MessageRow.thread_ref.in_(threads)))


def get_thread_timeline(
    session: Session,
    company_id: UUID,
    person_id: UUID | None = None,
    unit_id: UUID | None = None,
    case_id: UUID | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fast SQL chronological timeline of messages matching person, unit, or case."""
    stmt = (
        select(MessageRow)
        .where(MessageRow.company_id == company_id, not_chat_only())
        .order_by(MessageRow.sent_at.desc())
        .limit(limit)
    )
    if person_id is not None:
        stmt = stmt.where(MessageRow.person_id == person_id)
    if unit_id is not None or case_id is not None:
        stmt = stmt.where(_in_cases(company_id, case_id, unit_id))

    rows = session.scalars(stmt).all()
    return [
        {
            "message_id": str(m.id),
            "sent_at": m.sent_at.isoformat(),
            "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
            "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction),
            "sender": m.sender_identity,
            "snippet": " ".join(m.text.split())[:200] if m.text else "",
        }
        for m in rows
    ]

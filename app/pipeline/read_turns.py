"""Super Agent conversation reads (API, SSE, the turn brief). Every function requires `company_id` (invariant 4);
conversations are also scoped to their owner, so one owner never sees another owner's chat."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.db.enums import TurnStatus
from app.db.models import AgentConversation, AgentTurn

MAX_CONVERSATION_TURNS = 50
MAX_TURN_EVENTS = 100
TurnCursor = tuple[datetime, UUID]


def owns_conversation(session: Session, company_id: UUID, owner_id: UUID, conversation_id: UUID) -> bool:
    found = session.scalar(
        select(AgentConversation.id).where(
            AgentConversation.company_id == company_id,
            AgentConversation.owner_id == owner_id,
            AgentConversation.id == conversation_id,
        )
    )
    return found is not None


def conversation_turns(
    session: Session, company_id: UUID, owner_id: UUID, conversation_id: UUID
) -> list[AgentTurn] | None:
    """Oldest first, the newest `MAX_CONVERSATION_TURNS`; None for a missing, foreign or other owner's conversation."""
    if not owns_conversation(session, company_id, owner_id, conversation_id):
        return None
    newest = session.scalars(
        select(AgentTurn)
        .where(AgentTurn.company_id == company_id, AgentTurn.conversation_id == conversation_id)
        .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc())
        .limit(MAX_CONVERSATION_TURNS)
    ).all()
    return list(reversed(newest))


def earlier_exchanges(
    session: Session, company_id: UUID, conversation_id: UUID, before: TurnCursor, limit: int
) -> list[tuple[str, str | None, TurnStatus]]:
    """(owner text, answer, status) of the `limit` answered, not failed turns before `before` (created_at, id) in the
    conversation, oldest first. The conversation is joined on the company, so a foreign conversation yields nothing."""
    rows = session.execute(
        select(AgentTurn.text, AgentTurn.answer, AgentTurn.status)
        .join(
            AgentConversation,
            (AgentConversation.id == AgentTurn.conversation_id) & (AgentConversation.company_id == company_id),
        )
        .where(
            AgentTurn.company_id == company_id,
            AgentTurn.conversation_id == conversation_id,
            AgentTurn.status == TurnStatus.done,
            AgentTurn.answer.is_not(None),
            tuple_(AgentTurn.created_at, AgentTurn.id) < tuple_(*before),
        )
        .order_by(AgentTurn.created_at.desc(), AgentTurn.id.desc())
        .limit(limit)
    ).all()
    return [(r.text, r.answer, r.status) for r in reversed(rows)]


def turns_changed_after(
    session: Session, company_id: UUID, owner_id: UUID, after: TurnCursor, limit: int = MAX_TURN_EVENTS
) -> list[AgentTurn]:
    """Turns of this owner whose `updated_at` passed the cursor, in cursor order (SSE `turn` events)."""
    q = (
        select(AgentTurn)
        .join(
            AgentConversation,
            (AgentConversation.id == AgentTurn.conversation_id) & (AgentConversation.company_id == company_id),
        )
        .where(
            AgentTurn.company_id == company_id,
            AgentConversation.owner_id == owner_id,
            tuple_(AgentTurn.updated_at, AgentTurn.id) > tuple_(*after),
        )
        .order_by(AgentTurn.updated_at, AgentTurn.id)
        .limit(max(1, min(limit, MAX_TURN_EVENTS)))
    )
    return list(session.scalars(q))

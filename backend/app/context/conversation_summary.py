"""T2 Conversation Memory: Rolling conversation summary (spec §6.1, §6.2, Task C9).

Maintains rolling summaries (≤ 1200 chars) for agent_conversations, triggered every 6th turn.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.enums import TurnStatus
from app.db.models import AgentConversation, AgentTurn

MAX_SUMMARY_CHARS = 1200
TURNS_PER_SUMMARY = 6


def count_unsummarized_turns(
    session: Session,
    company_id: UUID,
    conversation_id: UUID,
    since_turn_id: UUID | None = None,
) -> int:
    """Count completed turns in this conversation since the last summarized turn."""
    query = select(func.count(AgentTurn.id)).where(
        AgentTurn.company_id == company_id,
        AgentTurn.conversation_id == conversation_id,
        AgentTurn.status == TurnStatus.done,
    )
    if since_turn_id is not None:
        turn = session.get(AgentTurn, since_turn_id)
        if turn is not None:
            query = query.where(AgentTurn.created_at > turn.created_at)
    return session.scalar(query) or 0


def should_summarize(unsummarized_count: int) -> bool:
    """Whether enough new turns have accumulated to trigger a rolling summary."""
    return unsummarized_count >= TURNS_PER_SUMMARY


def summarize_conversation_rolling(
    previous_summary: str,
    new_exchanges: Sequence[tuple[str, str]],
) -> str:
    """Build a deterministic rolling summary bounded to MAX_SUMMARY_CHARS.

    Can be augmented by LLM on context queue; this provides a robust, fast deterministic baseline.
    """
    items: list[str] = []
    if previous_summary.strip():
        items.append(f"Earlier: {previous_summary.strip()}")

    for q, a in new_exchanges:
        q_clean = " ".join(q.split())[:150]
        a_clean = " ".join(a.split())[:150]
        items.append(f"Q: {q_clean} -> A: {a_clean}")

    full = " | ".join(items)
    if len(full) <= MAX_SUMMARY_CHARS:
        return full
    return full[-MAX_SUMMARY_CHARS:]


def update_conversation_summary(
    session: Session,
    company_id: UUID,
    conversation_id: UUID,
    summary: str,
    through_turn_id: UUID,
    *,
    expected_version: int,
) -> bool:
    """Compare-and-swap on `summary_version` to prevent concurrent write collisions."""
    capped = summary[:MAX_SUMMARY_CHARS]
    result = session.execute(
        update(AgentConversation)
        .where(
            AgentConversation.id == conversation_id,
            AgentConversation.company_id == company_id,
            AgentConversation.summary_version == expected_version,
        )
        .values(
            summary=capped,
            summary_through=through_turn_id,
            summary_version=expected_version + 1,
        )
    )
    session.expire_all()
    return bool(result.rowcount)  # type: ignore[attr-defined]

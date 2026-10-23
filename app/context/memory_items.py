"""T5 Preferences & Standing Memory management (spec §6.2, §6.3, §6.4, §8, Task C11).

Handles owner-declared rules ('remember ...', 'from now on ...'), preference storage, safety screening,
and semantic memory retrieval via pgvector embeddings.
"""

import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import MemoryItem
from app.llm.render import data_block, escape

FORBIDDEN_PHRASES = (
    "skip approval",
    "without approval",
    "no approval",
    "auto send",
    "send automatically",
    "send without",
    "never ask",
    "geen goedkeuring",
    "zonder goedkeuring",
    "automatisch verzenden",
)

REFUSAL_MESSAGE = (
    "EstateOS cannot remember rules that bypass owner approval or automate message sending. "
    "All tenant messages and outbound actions always require your review."
)


def screen_memory_text(text: str) -> str | None:
    """Returns REFUSAL_MESSAGE if text attempts to bypass approval or automate sending, else None."""
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lowered:
            return REFUSAL_MESSAGE
    return None


def normalize_memory_text(text: str) -> str:
    """Normalize control characters and collapse whitespace."""
    clean = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in text)
    return " ".join(clean.split())[:300]


def record_owner_memory(
    session: Session,
    company_id: UUID,
    text: str,
    *,
    scope: MemoryScope = MemoryScope.company,
    scope_id: UUID | None = None,
    kind: MemoryKind = MemoryKind.rule,
) -> tuple[MemoryItem | None, str]:
    """Record an immediate owner preference or rule (Task C11).

    Screens against approval bypass and inserts or increments evidence count.
    """
    refusal = screen_memory_text(text)
    if refusal is not None:
        return None, refusal

    clean_text = normalize_memory_text(text)
    if not clean_text:
        return None, "Empty memory content."

    # Upsert: if already active for this company/scope/text, increment evidence_count
    existing = session.scalar(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id,
            MemoryItem.scope == scope,
            MemoryItem.scope_id == scope_id,
            MemoryItem.status == MemoryStatus.active,
            MemoryItem.text == clean_text,
        )
    )
    if existing is not None:
        existing.evidence_count += 1
        existing.last_used_at = datetime.now(tz=UTC)
        session.flush()
        return existing, f"Remembered (updated evidence count: {existing.evidence_count})."

    item = MemoryItem(
        id=new_id(),
        company_id=company_id,
        scope=scope,
        scope_id=scope_id,
        kind=kind,
        text=clean_text,
        status=MemoryStatus.active,
        origin=MemoryOrigin.owner,
        source_refs=[],
        evidence_count=1,
        confidence=1.0,
        last_used_at=datetime.now(tz=UTC),
    )
    session.add(item)
    session.flush()
    return item, f"Remembered: '{clean_text}'"


def get_active_preferences(
    session: Session,
    company_id: UUID,
    *,
    scope_ids: Sequence[UUID] = (),
    limit: int = 10,
) -> list[MemoryItem]:
    """Retrieve active owner preferences for company and focused entities, ordered by evidence count."""
    query = (
        select(MemoryItem)
        .where(
            MemoryItem.company_id == company_id,
            MemoryItem.status == MemoryStatus.active,
            (MemoryItem.scope == MemoryScope.company)
            | (MemoryItem.scope_id.in_(list(scope_ids)) if scope_ids else False),
        )
        .order_by(MemoryItem.evidence_count.desc(), MemoryItem.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(query).all())


def format_owner_preferences_block(items: Sequence[MemoryItem]) -> str | None:
    """Render active owner preferences in a protected data block for prompt injection."""
    if not items:
        return None
    lines: list[str] = []
    for item in items:
        # Only owner-origin or approved items are rendered
        if item.origin == MemoryOrigin.owner or item.status == MemoryStatus.active:
            clean = " ".join(item.text.split())
            lines.append(f"- {escape(clean, 'owner_preferences')}")
    if not lines:
        return None
    return data_block("owner_preferences", "\n".join(lines))


def retire_memory(session: Session, company_id: UUID, memory_id: UUID) -> bool:
    """Retire a memory item so it is excluded from active prompts."""
    item = session.scalar(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id,
            MemoryItem.id == memory_id,
        )
    )
    if item is None:
        return False
    item.status = MemoryStatus.retired
    session.flush()
    return True

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

from app.context.memory_dedup import find_near_duplicate
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
    status: MemoryStatus = MemoryStatus.active,
) -> tuple[MemoryItem | None, str]:
    """Record an immediate or proposed owner preference/rule (Task C11).

    Screens against approval bypass and inserts or increments evidence count.
    """
    refusal = screen_memory_text(text)
    if refusal is not None:
        return None, refusal

    clean_text = normalize_memory_text(text)
    if not clean_text:
        return None, "Empty memory content."

    # Upsert: if already active or proposed for this company/scope/text
    existing = session.scalar(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id,
            MemoryItem.scope == scope,
            MemoryItem.scope_id == scope_id,
            MemoryItem.status.in_((MemoryStatus.active, MemoryStatus.proposed)),
            MemoryItem.text == clean_text,
        )
    )
    if existing is None:
        existing = find_near_duplicate(
            session,
            company_id,
            scope,
            scope_id,
            clean_text,
            (MemoryStatus.active,),
            kind=kind,
            origin=MemoryOrigin.owner,
        )
    if existing is not None:
        if existing.status == MemoryStatus.active:
            existing.evidence_count += 1
            existing.last_used_at = datetime.now(tz=UTC)
            session.flush()
            return existing, f"Remembered (updated evidence count: {existing.evidence_count}): '{existing.text}'"
        return existing, "Rule is already proposed and pending activation."

    item = MemoryItem(
        id=new_id(),
        company_id=company_id,
        scope=scope,
        scope_id=scope_id,
        kind=kind,
        text=clean_text,
        status=status,
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


def get_memory_item(session: Session, company_id: UUID, memory_id: UUID) -> MemoryItem | None:
    """Retrieve a single memory item for the given company."""
    return session.scalar(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id,
            MemoryItem.id == memory_id,
        )
    )


def list_memory_items(
    session: Session,
    company_id: UUID,
    *,
    status: MemoryStatus | None = None,
    scope: MemoryScope | None = None,
    kind: MemoryKind | None = None,
    limit: int = 50,
) -> list[MemoryItem]:
    """List memory items with company isolation, optional filters, and bounded pagination."""
    query = select(MemoryItem).where(MemoryItem.company_id == company_id)
    if status is not None:
        query = query.where(MemoryItem.status == status)
    if scope is not None:
        query = query.where(MemoryItem.scope == scope)
    if kind is not None:
        query = query.where(MemoryItem.kind == kind)
    capped = min(max(1, limit), 100)
    query = query.order_by(MemoryItem.created_at.desc(), MemoryItem.id.desc()).limit(capped)
    return list(session.scalars(query).all())


def update_memory_item(
    session: Session,
    company_id: UUID,
    memory_id: UUID,
    *,
    text: str | None = None,
    status: MemoryStatus | None = None,
    scope: MemoryScope | None = None,
    scope_id: UUID | None = None,
    kind: MemoryKind | None = None,
) -> tuple[MemoryItem | None, str | None]:
    """Update a memory item with validation and screening (Task C11)."""
    item = get_memory_item(session, company_id, memory_id)
    if item is None:
        return None, "Not found"

    if text is not None:
        refusal = screen_memory_text(text)
        if refusal is not None:
            return None, refusal
        clean_text = normalize_memory_text(text)
        if not clean_text:
            return None, "Memory text cannot be empty"
        item.text = clean_text

    if status is not None:
        item.status = status
    if scope is not None:
        item.scope = scope
    if scope_id is not None:
        item.scope_id = scope_id
    if kind is not None:
        item.kind = kind

    item.updated_at = datetime.now(tz=UTC)
    session.flush()
    return item, None


def retire_memory(session: Session, company_id: UUID, memory_id: UUID) -> bool:
    """Retire a memory item so it is excluded from active prompts."""
    item = get_memory_item(session, company_id, memory_id)
    if item is None:
        return False
    item.status = MemoryStatus.retired
    item.updated_at = datetime.now(tz=UTC)
    session.flush()
    return True


def sweep_retired_memories(session: Session, company_id: UUID, cutoff: datetime) -> int:
    """Retire active memories unused for >= 180 days (spec §6.3, Task C11)."""
    from sqlalchemy import and_, or_, update

    result = session.execute(
        update(MemoryItem)
        .where(
            MemoryItem.company_id == company_id,
            MemoryItem.status == MemoryStatus.active,
            or_(
                and_(MemoryItem.last_used_at.is_not(None), MemoryItem.last_used_at < cutoff),
                and_(MemoryItem.last_used_at.is_(None), MemoryItem.created_at < cutoff),
            ),
        )
        .values(status=MemoryStatus.retired, updated_at=datetime.now(tz=UTC))
    )
    session.flush()
    return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult from a DML statement

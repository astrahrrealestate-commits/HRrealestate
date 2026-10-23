"""Nightly memory distiller (spec §6.3, Task C11).

Compares agent draft vs owner-edited text from `action_revisions`, proposes up to 3 candidate
`memory_items` (`status=proposed`, `origin=distilled`), delivers `memory_review` cards to the owner feed,
and retires standing memories unused for >= 180 days.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.context.memory_items import (
    normalize_memory_text,
    screen_memory_text,
    sweep_retired_memories,
)
from app.contracts import OwnerChoice, OwnerMessage
from app.core.ids import new_id
from app.core.logging import get_logger
from app.db.enums import FeedKind, MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import ActionRevision, ActionRow, MemoryItem

log = get_logger(__name__)
MAX_NIGHTLY_PROPOSALS = 3
DEFAULT_UNUSED_DAYS = 180


class DistilledProposal(BaseModel):
    rule: str = Field(min_length=5, max_length=300)
    confidence: float = 0.85
    kind: MemoryKind = MemoryKind.preference


def _extract_text(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    for key in ("body", "text", "message", "content"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def find_candidate_revisions(
    session: Session,
    company_id: UUID,
    *,
    since: datetime | None = None,
    limit: int = 20,
) -> list[tuple[ActionRevision, ActionRow]]:
    """Find recent owner-edited revisions whose actions originated as agent proposals."""
    query = (
        select(ActionRevision, ActionRow)
        .join(ActionRow, (ActionRow.id == ActionRevision.action_id) & (ActionRow.company_id == company_id))
        .where(
            ActionRevision.company_id == company_id,
            ActionRevision.edited_by.startswith("owner"),
        )
    )
    if since is not None:
        query = query.where(ActionRevision.created_at >= since)
    query = query.order_by(ActionRevision.created_at.desc()).limit(limit)
    return list(session.execute(query).all())


def propose_distilled_memory(
    session: Session,
    company_id: UUID,
    text: str,
    *,
    kind: MemoryKind = MemoryKind.preference,
    scope: MemoryScope = MemoryScope.company,
    scope_id: UUID | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    confidence: float = 0.85,
) -> MemoryItem | None:
    """Propose a distilled memory item or increment evidence if already proposed/active (spec §6.3)."""
    refusal = screen_memory_text(text)
    if refusal is not None:
        log.info("distiller.rejected_by_screen", company_id=str(company_id), text=text)
        return None

    clean = normalize_memory_text(text)
    if not clean:
        return None

    # Check for existing item with matching text (case-insensitive) under company & scope where status != retired
    existing = session.scalar(
        select(MemoryItem).where(
            MemoryItem.company_id == company_id,
            MemoryItem.scope == scope,
            MemoryItem.scope_id == scope_id,
            MemoryItem.status != MemoryStatus.retired,
            MemoryItem.text == clean,
        )
    )
    refs = list(source_refs or [])
    if existing is not None:
        existing.evidence_count += 1
        existing.confidence = min(1.0, existing.confidence + 0.05)
        if refs:
            current_refs = list(existing.source_refs or [])
            current_refs.extend(refs)
            existing.source_refs = current_refs
        session.flush()
        log.info("distiller.evidence_incremented", memory_id=str(existing.id), count=existing.evidence_count)
        return existing

    item = MemoryItem(
        id=new_id(),
        company_id=company_id,
        scope=scope,
        scope_id=scope_id,
        kind=kind,
        text=clean,
        status=MemoryStatus.proposed,
        origin=MemoryOrigin.distilled,
        source_refs=refs,
        evidence_count=1,
        confidence=confidence,
    )
    session.add(item)
    session.flush()

    # Deliver to owner feed
    msg = OwnerMessage(
        text=f'The agent noticed an edit to your draft:\n"{clean}"\nShould this become a standing preference?',
        header="Proposed Preference",
        choices=(
            OwnerChoice(id=f"memreview:{item.id}:approve", label="Approve"),
            OwnerChoice(id=f"memreview:{item.id}:reject", label="Dismiss"),
        ),
    )
    feed.deliver(session, company_id, f"memreview:{item.id}", FeedKind.memory_review, item.id, msg)
    log.info("distiller.memory_proposed", company_id=str(company_id), memory_id=str(item.id))
    return item


def distill_company(
    session: Session,
    company_id: UUID,
    now: datetime,
    *,
    proposals_limit: int = MAX_NIGHTLY_PROPOSALS,
    unused_days: int = DEFAULT_UNUSED_DAYS,
) -> tuple[int, int]:
    """Run nightly distiller for a company.

    1. Analyzes owner revisions to propose <= 3 candidate preferences.
    2. Sweeps memories unused for >= unused_days to retired.
    Returns (proposed_count, retired_count).
    """
    since = now - timedelta(days=2)  # look at past 48 hours for unanalyzed revisions
    candidates = find_candidate_revisions(session, company_id, since=since, limit=20)

    proposed_count = 0
    for rev, action in candidates:
        if proposed_count >= proposals_limit:
            break

        original_text = _extract_text(action.payload)
        revised_text = _extract_text(rev.payload)
        if not original_text or not revised_text or original_text == revised_text:
            continue

        # In standard extraction: summarize preference observed in the edit
        # Example: if revised text is significantly shorter or has specific instruction
        distilled_text = f"Preference observed from edit on action {action.type}: {revised_text[:120]}"
        item = propose_distilled_memory(
            session,
            company_id,
            distilled_text,
            source_refs=[{"action_id": str(action.id), "revision_id": str(rev.id)}],
        )
        if item is not None and item.status == MemoryStatus.proposed:
            proposed_count += 1

    # Retirement sweep
    cutoff = now - timedelta(days=unused_days)
    retired_count = sweep_retired_memories(session, company_id, cutoff)

    return proposed_count, retired_count

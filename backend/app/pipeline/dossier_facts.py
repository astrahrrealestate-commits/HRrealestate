"""Owner rules and open waits for a dossier (M13)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.context.memory_items import get_active_preferences
from app.db.enums import WaitStatus
from app.db.models import WaitRow

MAX_RULES = 20


def open_waits(session: Session, company_id: UUID, case_id: UUID | None) -> tuple[str, ...]:
    if case_id is None:
        return ()
    rows = session.scalars(
        select(WaitRow.about).where(
            WaitRow.company_id == company_id, WaitRow.case_id == case_id, WaitRow.status == WaitStatus.waiting
        )
    )
    return tuple(rows)


def owner_rules(session: Session, company_id: UUID, scope_ids: Sequence[UUID | None]) -> tuple[str, ...]:
    """Harjot's active standing rules for the company and for this person, case or unit."""
    ids = [i for i in scope_ids if i is not None]
    items = get_active_preferences(session, company_id, scope_ids=ids, limit=MAX_RULES)
    return tuple(" ".join(item.text.split()) for item in items)

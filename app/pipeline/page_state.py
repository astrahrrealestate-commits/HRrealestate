"""Page pre-warm (spec amendment 2026-10-22, Task 4): the owner's page facts, resolved before he types.

`PUT /agent/page` resolves the validated page company-scoped with the turn's own resolver and stored shape
(`concierge_page.resolved_value`) and upserts ONE `agent_page_state` row per owner. `create_turn` reuses those facts
only when the message's page has the same `page_key`, the row is the same company's and owner's (from the session,
never from client ids), and it was resolved at most `PAGE_TTL` before the turn's creation time (both on the
database clock: `now()` of the turn's own transaction is its `created_at`). Otherwise the turn resolves as before.
The snapshot and filters are never stored here: a turn always takes them from its message. The TTL applies at read
time only; the single row per owner is overwritten by the next PUT, so the table does not grow. Reads are plain
scoped SELECTs (no locks): a row overwritten in between is either still the same page (same facts) or a miss.
Logs carry ids and error types only (the facts hold tenant text).
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, Insert, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.contracts import PageContext
from app.core.ids import new_id
from app.core.logging import get_logger
from app.db.models import AgentPageState
from app.pipeline import concierge_page
from app.pipeline.concierge import is_transient

log = get_logger(__name__)
PAGE_TTL = timedelta(seconds=120)
CLOCK_SLACK = timedelta(seconds=5)  # a PUT whose transaction began just after the turn's: still the same page
KEY_VERSION = "v1"


def page_key(page: PageContext) -> str:
    """A hash of what the resolved facts depend on: the view, each open id in its own field and the visible ids in
    screen order (the facts list them in that order for "the first one"). Snapshot and filters are not part of it
    (never resolved). Computed from the validated context, so ids are in their normal form; no raw id is kept."""
    canonical = {
        "view": page.view.value,
        "case_id": str(page.case_id) if page.case_id else None,
        "thread_key": page.thread_key,
        "approval_id": str(page.approval_id) if page.approval_id else None,
        "task_ref": page.task_ref,
        "attachment_id": str(page.attachment_id) if page.attachment_id else None,
        "visible_ids": list(page.visible_ids),
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return f"{KEY_VERSION}:{hashlib.sha256(text.encode()).hexdigest()}"


def reusable(stored_key: str, resolved_at: datetime, key: str, now: datetime, ttl: timedelta = PAGE_TTL) -> bool:
    """Warmed facts serve a turn only for the same page, resolved at most `ttl` before `now` (the turn's time)."""
    age = now - resolved_at
    return stored_key == key and -CLOCK_SLACK <= age <= ttl


def _shape(value: Any) -> dict[str, Any] | None:
    """The stored value when it has the exact `resolved` shape of a successful resolution, else None."""
    if not isinstance(value, dict) or set(value) != {"facts", "dropped"} or not isinstance(value["facts"], str):
        return None
    dropped = value["dropped"]
    if not isinstance(dropped, list) or not all(isinstance(kind, str) for kind in dropped):
        return None
    return {"facts": value["facts"], "dropped": list(dropped)}


def warm_resolved(session: Session, company_id: UUID, owner_id: UUID, page: PageContext) -> dict[str, Any] | None:
    """This owner's warmed facts for exactly this page, when still fresh; None otherwise."""
    row = session.execute(
        select(AgentPageState.page_key, AgentPageState.resolved_at, AgentPageState.resolved, func.now()).where(
            AgentPageState.company_id == company_id, AgentPageState.owner_id == owner_id
        )
    ).one_or_none()
    if row is None:
        return None
    stored_key, resolved_at, resolved, now = row
    if not reusable(stored_key, resolved_at, page_key(page), now):
        return None
    return _shape(resolved)


def turn_page_context(session: Session, company_id: UUID, owner_id: UUID, page: PageContext) -> dict[str, Any]:
    """The `page_context` a new turn stores: the message's validated page (its own snapshot and filters), plus the
    warmed facts under `resolved` when they match, so the run skips resolving exactly as a retry does."""
    value = page.model_dump(mode="json")
    resolved = warm_resolved(session, company_id, owner_id, page)
    return value if resolved is None else {**value, concierge_page.RESOLVED: resolved}


def _upsert(company_id: UUID, owner_id: UUID, key: str, resolved: dict[str, Any]) -> Insert:
    """One row per owner; never moved to another company; an older resolution never overwrites a newer one."""
    stmt = insert(AgentPageState).values(
        id=new_id(), company_id=company_id, owner_id=owner_id, page_key=key, resolved=resolved, resolved_at=func.now()
    )
    return stmt.on_conflict_do_update(
        index_elements=[AgentPageState.owner_id],
        set_={"page_key": stmt.excluded.page_key, "resolved": stmt.excluded.resolved,
              "resolved_at": stmt.excluded.resolved_at},
        where=(AgentPageState.company_id == stmt.excluded.company_id)
        & (AgentPageState.resolved_at <= stmt.excluded.resolved_at),
    )  # fmt: skip


def warm(engine: Engine, company_id: UUID, owner_id: UUID, page: PageContext) -> bool:
    """Resolve and store the owner's page facts in one transaction (`resolved_at` = its start, so the facts are never
    older than it says). Transient errors propagate (the route answers 503); any other error stores nothing and
    returns False (the turn then resolves as usual)."""
    try:
        with Session(engine) as session, session.begin():
            resolved = concierge_page.resolved_value(session, company_id, page)
            session.execute(_upsert(company_id, owner_id, page_key(page), resolved))
    except Exception as exc:
        if is_transient(exc):
            raise
        log.error("dashboard.page_warm_failed", company_id=str(company_id), error=type(exc).__name__)
        return False
    return True

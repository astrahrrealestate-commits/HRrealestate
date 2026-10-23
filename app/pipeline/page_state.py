"""Page pre-warm (spec amendment 2026-10-22, Task 4): the owner's page facts, resolved before he types.

`PUT /agent/page` resolves the validated page company-scoped with the turn's own resolver and stored shape
(`concierge_page.resolved_value`) and upserts ONE `agent_page_state` row per owner. `create_turn` reuses those facts
only when the message's page has the same `page_key`, the row is the same company's and owner's (from the session,
never from client ids), it was resolved at most `PAGE_TTL` before the turn's creation time (both on the database
clock: `now()` of the turn's own transaction is its `created_at`), and nothing the facts are built from changed in
the company since: no newer message, approval (created or decided) or case event (`latest_change`, with a small
margin for writes racing the resolve). Otherwise the turn resolves as before; a failed read never fails the message.
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

from sqlalchemy import DateTime, Engine, Insert, Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.context.focus_trail import append_focus_trail, page_to_focus_item
from app.contracts import PageContext
from app.core.ids import new_id
from app.core.logging import get_logger
from app.db.models import AgentPageState, Approval, CaseEvent, MessageRow
from app.pipeline import concierge_page
from app.pipeline.concierge import is_transient

log = get_logger(__name__)
PAGE_TTL = timedelta(seconds=120)
CLOCK_SLACK = timedelta(seconds=5)  # a PUT whose transaction began just after the turn's: still the same page
KEY_VERSION = "v1"
FRESHNESS_MARGIN = timedelta(seconds=2)  # a write whose transaction began just before the resolve may be missing


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


def unchanged_since(latest_change: datetime | None, resolved_at: datetime) -> bool:
    """Nothing the facts are built from changed since they were resolved: no change at all, or the newest one
    strictly older than `resolved_at - FRESHNESS_MARGIN`. Equal or inside the margin counts as changed (cold)."""
    return latest_change is None or latest_change < resolved_at - FRESHNESS_MARGIN


def latest_change(company_id: UUID) -> Select[datetime | None]:
    """One statement: the company's newest message, approval created or decided, or case event (each a max() over
    a (company_id, column) index, migration 0016). `greatest` ignores NULLs; NULL only when there are no rows."""
    newest = [
        select(func.max(column)).where(table_company == company_id).scalar_subquery()
        for column, table_company in (
            (MessageRow.created_at, MessageRow.company_id),
            (Approval.created_at, Approval.company_id),
            (Approval.decided_at, Approval.company_id),
            (CaseEvent.created_at, CaseEvent.company_id),
        )
    ]
    return select(func.greatest(*newest, type_=DateTime(timezone=True)))


def _shape(value: Any) -> dict[str, Any] | None:
    """The stored value when it has the exact `resolved` shape of a successful resolution, else None."""
    if not isinstance(value, dict) or set(value) != {"facts", "dropped"} or not isinstance(value["facts"], str):
        return None
    dropped = value["dropped"]
    if not isinstance(dropped, list) or not all(isinstance(kind, str) for kind in dropped):
        return None
    return {"facts": value["facts"], "dropped": list(dropped)}


def warm_resolved(session: Session, company_id: UUID, owner_id: UUID, page: PageContext) -> dict[str, Any] | None:
    """This owner's warmed facts for exactly this page, when still fresh and nothing changed since; else None."""
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
    if not unchanged_since(session.scalar(latest_change(company_id)), resolved_at):
        return None
    return _shape(resolved)


def turn_page_context_with_hit(
    session: Session, company_id: UUID, owner_id: UUID, page: PageContext
) -> tuple[dict[str, Any], str]:
    """The `page_context` a new turn stores, plus the warm_hit label ("none" | "facts")."""
    value = page.model_dump(mode="json")
    try:
        with session.begin_nested():
            resolved = warm_resolved(session, company_id, owner_id, page)
    except Exception as exc:
        if is_transient(exc):
            raise
        log.warning("dashboard.page_state_read_failed", company_id=str(company_id), error=type(exc).__name__)
        return value, "none"
    if resolved is None:
        return value, "none"
    return {**value, concierge_page.RESOLVED: resolved}, "facts"


def turn_page_context(session: Session, company_id: UUID, owner_id: UUID, page: PageContext) -> dict[str, Any]:
    """The `page_context` a new turn stores: the message's validated page (its own snapshot and filters), plus the
    warmed facts under `resolved` when they match, so the run skips resolving exactly as a retry does."""
    ctx, _ = turn_page_context_with_hit(session, company_id, owner_id, page)
    return ctx


def _upsert(
    company_id: UUID,
    owner_id: UUID,
    key: str,
    resolved: dict[str, Any],
    focus_trail: list[dict[str, Any]] | None = None,
) -> Insert:
    """One row per owner; never moved to another company; an older resolution never overwrites a newer one."""
    trail = focus_trail or []
    stmt = insert(AgentPageState).values(
        id=new_id(),
        company_id=company_id,
        owner_id=owner_id,
        page_key=key,
        resolved=resolved,
        resolved_at=func.now(),
        focus_trail=trail,
    )
    return stmt.on_conflict_do_update(
        index_elements=[AgentPageState.owner_id],
        set_={
            "page_key": stmt.excluded.page_key,
            "resolved": stmt.excluded.resolved,
            "resolved_at": stmt.excluded.resolved_at,
            "focus_trail": stmt.excluded.focus_trail,
        },
        where=(AgentPageState.company_id == stmt.excluded.company_id)
        & (AgentPageState.resolved_at <= stmt.excluded.resolved_at),
    ).returning(AgentPageState.id)


def warm(engine: Engine, company_id: UUID, owner_id: UUID, page: PageContext) -> bool:
    """Resolve and store the owner's page facts in one transaction (`resolved_at` = its start, so the facts are never
    older than it says). True when the row was written; False when the upsert guard kept the stored row (another
    company's, or a newer resolution). Transient errors propagate (the route answers 503); any other error stores
    nothing and returns False (the turn then resolves as usual)."""
    try:
        with Session(engine) as session, session.begin():
            existing_trail = session.scalar(
                select(AgentPageState.focus_trail).where(
                    AgentPageState.company_id == company_id, AgentPageState.owner_id == owner_id
                )
            )
            focus_item = page_to_focus_item(page)
            new_trail = append_focus_trail(existing_trail or [], focus_item)
            resolved = concierge_page.resolved_value(session, company_id, page)
            written = session.execute(
                _upsert(company_id, owner_id, page_key(page), resolved, new_trail)
            ).scalar_one_or_none()
    except Exception as exc:
        if is_transient(exc):
            raise
        log.error("dashboard.page_warm_failed", company_id=str(company_id), error=type(exc).__name__)
        return False
    return written is not None

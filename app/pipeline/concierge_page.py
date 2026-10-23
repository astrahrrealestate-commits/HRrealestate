"""The page context of a Super Agent turn at run time (spec amendment 2026-10-16).

`agent_turns.page_context` holds the validated `PageContext` JSON written by `create_turn`. The first run resolves
its server facts once and the caller stores them under `resolved` BEFORE the model call, so a retried run (crash,
transient error) reuses exactly the same facts instead of re-resolving against a changed database. A non-transient
resolver error leaves the turn without facts (stored the same way) rather than failing it; transient errors propagate
so the DBOS step retries. The snapshot and filters are unverified client text: they only reach the model inside the
escaped `<page_snapshot>` block and are never parsed for ids.
`stored_prompt` is pure: the planner, the `answer` step and the planner-failure fallback all read the page from the
stored context. A turn stored before the facts were resolved (v1-era rows) gets no page.
"""

from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import PageContext
from app.core.logging import get_logger
from app.llm.page_blocks import NO_PAGE, PagePrompt
from app.pipeline.concierge import is_transient
from app.pipeline.page_facts import facts_text, resolve_page_facts

log = get_logger(__name__)
RESOLVED = "resolved"


def stored_page(stored: dict[str, Any] | None) -> tuple[PageContext | None, dict[str, Any] | None]:
    """The validated context and its stored resolution (None before the first run resolved it)."""
    if not stored:
        return None, None
    resolved = stored.get(RESOLVED)
    try:
        page = PageContext.model_validate({k: v for k, v in stored.items() if k != RESOLVED})
    except ValidationError:
        log.warning("concierge.page_context_invalid")
        return None, None
    return page, resolved if isinstance(resolved, dict) else None


def filters_line(page: PageContext) -> str:
    """The filters the page says are applied, as one unverified line (rendered before the snapshot)."""
    filters = "; ".join(f"{k}={v}" for k, v in page.filters.items())
    return f"filters: {' '.join(filters.split())}" if filters else ""


def resolved_value(session: Session, company_id: UUID, page: PageContext) -> dict[str, Any]:
    """The stored `resolved` shape (facts text and the dropped kinds), shared by a turn's first run and the page
    pre-warm (`page_state`), so warmed facts are exactly what the turn would have stored."""
    facts = resolve_page_facts(session, company_id, page)
    return {"facts": facts_text(facts), "dropped": list(facts.dropped)}


def _resolve(engine: Engine, company_id: UUID, page: PageContext) -> dict[str, Any]:
    try:
        with Session(engine) as session:
            return resolved_value(session, company_id, page)
    except Exception as exc:
        if is_transient(exc):
            raise
        log.error("concierge.page_facts_failed", company_id=str(company_id), error=type(exc).__name__)
        return {"facts": "", "dropped": [], "error": type(exc).__name__}


def resolve_once(engine: Engine, company_id: UUID, stored: dict[str, Any] | None) -> dict[str, Any] | None:
    """The new `page_context` value to store (request + `resolved`) when the page was not resolved yet; else None."""
    page, resolved = stored_page(stored)
    if page is None or resolved is not None:
        return None
    return {**page.model_dump(mode="json"), RESOLVED: _resolve(engine, company_id, page)}


def stored_prompt(stored: dict[str, Any] | None) -> PagePrompt:
    """The page part of a prompt from the stored context, without I/O; no page until its facts were resolved."""
    page, resolved = stored_page(stored)
    if page is None or resolved is None:
        return NO_PAGE
    return PagePrompt(str(resolved.get("facts") or ""), page.snapshot, filters_line(page))

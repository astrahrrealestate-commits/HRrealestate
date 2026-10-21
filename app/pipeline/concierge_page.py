"""The page context of a Super Agent turn at run time (spec amendment 2026-10-16).

`agent_turns.page_context` holds the validated `PageContext` JSON written by `create_turn`. The first run resolves
its server facts once and the caller stores them under `resolved` BEFORE the model call, so a retried run (crash,
transient error) reuses exactly the same facts instead of re-resolving against a changed database. A non-transient
resolver error leaves the turn without facts (stored the same way) rather than failing it; transient errors propagate
so the DBOS step retries. The snapshot and filters are unverified client text: they only reach the model inside the
escaped `<page_snapshot>` block and are never parsed for ids.
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


def _resolve(engine: Engine, company_id: UUID, page: PageContext) -> dict[str, Any]:
    try:
        with Session(engine) as session:
            facts = resolve_page_facts(session, company_id, page)
    except Exception as exc:
        if is_transient(exc):
            raise
        log.error("concierge.page_facts_failed", company_id=str(company_id), error=type(exc).__name__)
        return {"facts": "", "dropped": [], "error": type(exc).__name__}
    return {"facts": facts_text(facts), "dropped": list(facts.dropped)}


def page_prompt(
    engine: Engine, company_id: UUID, stored: dict[str, Any] | None
) -> tuple[PagePrompt, dict[str, Any] | None]:
    """The page part of the prompt, and the new `page_context` value to store when it was resolved just now."""
    page, resolved = stored_page(stored)
    if page is None:
        return NO_PAGE, None
    if resolved is not None:
        return PagePrompt(str(resolved.get("facts") or ""), page.snapshot, filters_line(page)), None
    fresh = _resolve(engine, company_id, page)
    prompt = PagePrompt(fresh["facts"], page.snapshot, filters_line(page))
    return prompt, {**page.model_dump(mode="json"), RESOLVED: fresh}

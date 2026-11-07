"""Shared pieces of the concierge executor: the step result, the per-run context and the fixed owner texts."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Engine

from app.contracts import Intent, PlanStep
from app.core.logging import get_logger
from app.core.settings import Settings
from app.llm.page_blocks import NO_PAGE, PagePrompt
from app.pipeline.turn_timings import TurnTimer

log = get_logger("app.pipeline.concierge")

NOT_FOUND = "I could not find that case/task"
NOT_SHOWN = "Open that case's page first, then ask again."  # a case id outside the brief and the page facts
NEED_DETAIL = "I need more detail"
STEP_FAILED = "Something went wrong with that step."


@dataclass(frozen=True)
class StepResult:
    intent: Intent
    ok: bool
    summary: str  # owner-facing text, safe: never unsanitised model text
    data: dict[str, Any] | None  # structured payload for the SPA (ids, rows)
    view: str | None


@dataclass(frozen=True)
class Researched:
    """What the read-only research loop (`app.superagent`) hands back: untrusted model text, plus step labels that carry
    tool names and counts only."""

    answer: str
    steps: tuple[str, ...] = ()


# (company_id, the owner's question, the turn's page) -> the loop's answer, or None when it has none (fake model,
# spent budget, failure). Injected by the workflow so the pipeline never imports the loop (layering, invariant 7).
Researcher = Callable[[UUID, str, PagePrompt], Researched | None]


@dataclass(frozen=True)
class Ctx:
    engine: Engine
    settings: Settings
    company_id: UUID
    now: datetime
    question: str  # the owner's own message (for the `answer` step), never the model's text
    page: PagePrompt = NO_PAGE  # the turn's stored page facts and snapshot (for the `answer` step); no I/O here
    memo: dict[str, StepResult] = field(default_factory=dict)  # per-plan results reused by later steps (answer)
    known_cases: frozenset[UUID] = frozenset()  # the only case ids a plan may name: the brief's and the page's
    turn_id: UUID | None = None  # with step_index, the key of an owner-requested redraft (None: no redraft)
    step_index: int = 0
    reply: str | None = None  # the plan's own answer (concierge/v3): the `answer` step screens and shows it
    timer: TurnTimer = field(default_factory=TurnTimer)  # the turn's stage clock (answer_ms of an owner_qa call)
    needs_research: bool = False  # concierge/v7: the `answer` step asks the research loop (read-only plans only)
    research: Researcher | None = None


Handler = Callable[[Ctx, PlanStep], StepResult]


def task_ref(raw: str | None) -> str | None:
    """A 6–8 hex task ref (`#` allowed), lower-cased; anything else (LIKE wildcards included) is None."""
    ref = (raw or "").strip().lstrip("#").lower()
    return ref if re.fullmatch(r"[0-9a-f]{6,8}", ref) else None


def failed(step: PlanStep, summary: str) -> StepResult:
    return StepResult(step.intent, False, summary, None, None)


def log_change(ctx: Ctx, step: PlanStep) -> None:
    """Every state change the executor makes; ids only, never free text."""
    log.info("concierge.changed", company_id=str(ctx.company_id), intent=step.intent.value)

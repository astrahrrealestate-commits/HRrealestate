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

log = get_logger("app.pipeline.concierge")

NOT_FOUND = "I could not find that case/task"
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
class Ctx:
    engine: Engine
    settings: Settings
    company_id: UUID
    now: datetime
    question: str  # the owner's own message (for the `answer` step), never the model's text
    memo: dict[str, StepResult] = field(default_factory=dict)  # per-plan results reused by later steps (answer)


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

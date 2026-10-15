"""Pure parts of a Super Agent turn: the prompt caps, the answer assembled from step results, what is stored, and
which fallback an exception gets. No I/O, so every rule here is unit-tested without a database."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python

from app.core.errors import AgentFailedError, BudgetExceededError
from app.db.enums import TurnStatus
from app.llm.agents.concierge import concierge_prompt
from app.llm.agents.owner_qa import CaseBrief
from app.pipeline.concierge import is_transient
from app.pipeline.concierge_base import StepResult
from app.pipeline.work_repo import short_ref

MAX_BRIEF_CASES = 20
MAX_BRIEF_TASKS = 20
MAX_HISTORY_TURNS = 4
PROMPT_REF = "concierge/v1"
EMPTY_PLAN = "I am not sure what to do with that. Try rephrasing it, or send `help` for the commands."
APOLOGY = "Sorry, something went wrong with that message. Please try again in a moment."


class Fallback(StrEnum):
    limit = "limit"  # budget spent: the fixed limit answer, the turn is still done
    owner_qa = "owner_qa"  # the planner failed: answer through owner_qa (then its fixed fallback)
    retry = "retry"  # transient infrastructure: re-raise so the DBOS step retries
    apology = "apology"  # anything else: the turn fails with a fixed apology


def fallback_for(exc: BaseException) -> Fallback:
    if isinstance(exc, BudgetExceededError):  # before AgentFailedError: it is a subclass
        return Fallback.limit
    if isinstance(exc, AgentFailedError):
        return Fallback.owner_qa
    if is_transient(exc):
        return Fallback.retry
    return Fallback.apology


@dataclass(frozen=True)
class Outcome:
    """What a finished turn stores. `plan`/`results` stay None on the fast path and on fallbacks."""

    answer: str
    plan: dict[str, Any] | None = None
    results: list[dict[str, Any]] | None = None
    prompt_ref: str | None = None
    status: TurnStatus = TurnStatus.done
    error: str | None = None


def failed_outcome(exc: BaseException) -> Outcome:
    """Only the exception type is kept: its text may quote message content."""
    return Outcome(APOLOGY, status=TurnStatus.failed, error=type(exc).__name__)


def task_brief(task_id: UUID, title: str) -> str:
    """One open task in the planner's data block: `#<ref> <title>`, so a plan can name it as `task_ref`."""
    return f"#{short_ref(task_id)} {title}"


def build_prompt(text: str, history: Sequence[str], cases: Sequence[CaseBrief], tasks: Sequence[str]) -> str:
    """The planner prompt with the brief capped: newest 20 cases and 20 tasks, the last 4 earlier turns."""
    return concierge_prompt(
        text,
        list(history)[-MAX_HISTORY_TURNS:],
        list(cases)[:MAX_BRIEF_CASES],
        list(tasks)[:MAX_BRIEF_TASKS],
    )


def result_json(result: StepResult) -> dict[str, Any]:
    return {
        "intent": result.intent.value,
        "ok": result.ok,
        "summary": result.summary,
        "data": to_jsonable_python(result.data),
        "view": result.view,
    }


def answer_lines(summaries: Sequence[str]) -> str:
    """One line per step summary, in plan order (deterministic: no second model call phrases it)."""
    lines = [s.strip() for s in summaries if s.strip()]
    return "\n".join(lines) or EMPTY_PLAN


def assemble_answer(results: Sequence[StepResult]) -> str:
    return answer_lines([r.summary for r in results])


def stored_answer(results: Sequence[dict[str, Any]]) -> str:
    """The answer of results stored by an earlier run (a retried turn finishes without executing again)."""
    return answer_lines([str(r.get("summary") or "") for r in results])

"""Pure parts of a Super Agent turn: the prompt caps, the answer assembled from step results, what is stored, and
which fallback an exception gets. No I/O, so every rule here is unit-tested without a database."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python

from app.context import CompiledContext, compile_concierge_context
from app.context.compiler import SUMMARY_PREFIX as SUMMARY_PREFIX
from app.core.errors import AgentFailedError, BudgetExceededError
from app.db.enums import TurnStatus
from app.llm.agents.concierge import CONCIERGE
from app.llm.agents.owner_qa import FALLBACK_ANSWER, CaseBrief
from app.llm.page_blocks import NO_PAGE, PagePrompt
from app.pipeline.concierge import is_transient
from app.pipeline.concierge_base import StepResult
from app.pipeline.owner_commands import LIMIT_ANSWER, CommandKind, fallback_command
from app.pipeline.work_repo import short_ref

MAX_BRIEF_CASES = 20
MAX_BRIEF_TASKS = 20
MAX_HISTORY_TURNS = 12
MAX_OWNER_CHARS = 1200
MAX_ANSWER_CHARS = 1200
PROMPT_REF = CONCIERGE.prompt.key
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
    """What a finished turn stores. `plan`/`results` stay None on fallbacks."""

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


NO_INFORMATION = (APOLOGY, FALLBACK_ANSWER, LIMIT_ANSWER, EMPTY_PLAN)


def _cap(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def history_lines(exchanges: Sequence[tuple[str, str | None, TurnStatus]]) -> list[str]:
    """`owner: ...` then `assistant: ...` lines of the last `MAX_HISTORY_TURNS` usable exchanges, oldest first.
    Failed turns, turns without an answer and the fixed texts that carry no information are skipped. The answers can
    quote tenant text, so these lines only ever reach a model through the escaped history block."""
    usable = [
        (text, answer)
        for text, answer, status in exchanges
        if status is TurnStatus.done and answer and answer.strip() not in NO_INFORMATION
    ]
    lines: list[str] = []
    for text, answer in usable[-MAX_HISTORY_TURNS:]:
        lines.append(f"owner: {_cap(text, MAX_OWNER_CHARS)}")
        lines.append(f"assistant: {_cap(answer, MAX_ANSWER_CHARS)}")
    return lines


def compile_prompt(
    text: str,
    history: Sequence[str],
    cases: Sequence[CaseBrief],
    tasks: Sequence[str],
    page: PagePrompt = NO_PAGE,
    entities: str = "",
    named_blocks: bool = False,
) -> CompiledContext:
    """Compile the concierge context using ContextSpec and return CompiledContext. `entities`: the people, units and
    cases the server matched to names in the question (`concierge_entities`), rendered."""
    summary = [h for h in history if h.startswith(SUMMARY_PREFIX)]
    turns = [h for h in history if not h.startswith(SUMMARY_PREFIX)]
    return compile_concierge_context(
        text,
        [*summary, *turns[-2 * MAX_HISTORY_TURNS :]],
        list(cases)[:MAX_BRIEF_CASES],
        list(tasks)[:MAX_BRIEF_TASKS],
        page.facts,
        page.snapshot,
        page.filters,
        entities=entities,
        named_blocks=named_blocks,
    )


def build_prompt(
    text: str,
    history: Sequence[str],
    cases: Sequence[CaseBrief],
    tasks: Sequence[str],
    page: PagePrompt = NO_PAGE,
) -> str:
    """The planner prompt with the brief capped: newest 20 cases and 20 tasks, the history lines already capped, and
    the page facts/snapshot (empty when the owner is not on a page). Byte-identical to concierge_prompt."""
    return compile_prompt(text, history, cases, tasks, page).prompt_text


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


def resumes(text: str, plan: dict[str, Any] | None, results: list[dict[str, Any]] | None) -> bool:
    """True only for the owner's own exact `resume` command run by the outage fallback (no plan, no results). A planned
    `resume` step never counts: the model (or an injected message) must not re-run approved actions."""
    cmd = fallback_command(text)
    return plan is None and results is None and cmd is not None and cmd.kind is CommandKind.resume

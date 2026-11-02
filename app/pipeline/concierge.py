"""Concierge executor (spec §4): validate every step of a ConciergePlan against the DB, then dispatch it.

A plan is untrusted model output. Out-of-scope plans run nothing. A `case_id` must be one the planner was shown as
company data (the brief's open cases or a case id on a resolved page-facts line); any other id, including one copied
from tenant text, gets "open that case's page first" (whether or not it exists). Each `case_id`/`task_ref` is then
resolved company-scoped before use; a bad step fails on its own and the plan goes on. A handler error fails only its
step, except transient infrastructure errors, which propagate so the calling DBOS step retries.
"""

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session

from app.contracts import ConciergePlan, Intent, PlanStep
from app.contracts.concierge import MAX_PLAN_STEPS
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.llm.agents.owner_qa import REFUSAL_ANSWER, page_case_ids
from app.llm.calls import is_transient as llm_transient
from app.llm.page_blocks import NO_PAGE, PagePrompt
from app.pipeline import (
    case_repo,
    concierge_chase,
    concierge_documents,
    concierge_proposals,
    concierge_reads,
    concierge_writes,
    work_repo,
)
from app.pipeline.concierge_base import (
    NEED_DETAIL,
    NOT_FOUND,
    NOT_SHOWN,
    STEP_FAILED,
    Ctx,
    Handler,
    StepResult,
    failed,
    log,
    task_ref,
)
from app.pipeline.concierge_reply import reply_allowed
from app.pipeline.turn_timings import TurnTimer

__all__ = [
    "MAX_STEPS",
    "StepResult",
    "check_step",
    "is_transient",
    "known_case_ids",
    "needs_detail",
    "run_plan",
    "validate_plan",
]

MAX_STEPS = MAX_PLAN_STEPS
_USES_CASE = frozenset(
    {
        Intent.case_status,
        Intent.draft_reply,
        Intent.show_drafts,
        Intent.chase_now,
        Intent.open_view,
        Intent.find_document,
        Intent.read_document,
    }
)
_NEEDS_CASE = frozenset({Intent.case_status, Intent.draft_reply, Intent.show_drafts, Intent.chase_now})
_NEEDS_TASK = frozenset({Intent.task_done, Intent.task_snooze})
_NEEDS_TEXT = frozenset(
    {Intent.task_snooze, Intent.create_task, Intent.clarify, Intent.search_inbox, Intent.find_document, Intent.query_data}
)

_HANDLERS: dict[Intent, Handler] = {
    Intent.answer: concierge_reads.answer,
    Intent.list_tasks: concierge_reads.list_tasks,
    Intent.list_waiting: concierge_reads.list_waiting,
    Intent.case_status: concierge_reads.case_status,
    Intent.search_inbox: concierge_reads.search_inbox,
    Intent.briefing_now: concierge_reads.briefing_now,
    Intent.file_document: concierge_reads.file_document,
    Intent.find_document: concierge_documents.find_document,
    Intent.read_document: concierge_documents.read_document,
    Intent.query_data: concierge_reads.query_data,
    Intent.open_view: concierge_reads.open_view,
    Intent.clarify: concierge_reads.clarify,
    Intent.task_done: concierge_writes.task_done,
    Intent.task_snooze: concierge_writes.task_snooze,
    Intent.create_task: concierge_writes.create_task,
    Intent.pause: concierge_writes.pause,
    Intent.resume: concierge_writes.resume,
    Intent.draft_reply: concierge_proposals.draft_reply,
    Intent.show_drafts: concierge_proposals.show_drafts,
    Intent.chase_now: concierge_chase.chase_now,
}


def needs_detail(step: PlanStep) -> bool:
    """A required argument of the intent is missing (pure: no DB)."""
    return (
        (step.intent in _NEEDS_CASE and step.case_id is None)
        or (step.intent in _NEEDS_TASK and not step.task_ref)
        or (step.intent in _NEEDS_TEXT and not (step.text or "").strip())
        or (step.intent is Intent.open_view and step.view is None)
    )


def _task_known(session: Session, company_id: UUID, raw: str | None) -> bool:
    ref = task_ref(raw)
    if ref is None:
        return False
    try:
        work_repo.resolve_task(session, company_id, ref)
    except NotFoundError:
        return False
    return True


def check_step(session: Session, company_id: UUID, step: PlanStep, known_cases: Collection[UUID]) -> str | None:
    """None when the step may run; otherwise the owner-facing reason (missing argument or unknown/foreign ref).
    `known_cases` are the case ids the planner was shown as company data; any other case id gets NOT_SHOWN."""
    if needs_detail(step):
        return NEED_DETAIL
    if step.intent in _USES_CASE and step.case_id is not None:
        if step.case_id not in known_cases:  # same text whether or not the id exists: no existence oracle
            return NOT_SHOWN
        try:
            case_repo.get_case(session, company_id, step.case_id)
        except NotFoundError:
            return NOT_FOUND
    if step.intent in _NEEDS_TASK and not _task_known(session, company_id, step.task_ref):
        return NOT_FOUND
    return None


def known_case_ids(brief_cases: Collection[UUID], page: PagePrompt) -> frozenset[UUID]:
    """The brief's case ids plus the case ids on the resolved page-facts lines (never the snapshot or tenant text)."""
    return frozenset(brief_cases) | frozenset(page_case_ids(page.facts))


def validate_plan(
    session: Session, company_id: UUID, plan: ConciergePlan, known_cases: Collection[UUID]
) -> list[PlanStep]:
    """The steps that may run, in order: nothing for an out-of-scope plan, at most MAX_STEPS."""
    if not plan.in_scope:
        return []
    return [s for s in plan.steps[:MAX_STEPS] if check_step(session, company_id, s, known_cases) is None]


def is_transient(exc: BaseException) -> bool:
    """Infrastructure hiccups the calling DBOS step should retry: DB connection/pool trouble, network, provider 5xx."""
    if bool(getattr(exc, "retryable", False)) or llm_transient(exc):
        return True
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    return isinstance(exc, OperationalError | InterfaceError | PoolTimeoutError | OSError)


def _run_step(ctx: Ctx, step: PlanStep) -> StepResult:
    try:
        with Session(ctx.engine) as session:
            problem = check_step(session, ctx.company_id, step, ctx.known_cases)
        if problem is not None:
            log.info("concierge.step_rejected", company_id=str(ctx.company_id), intent=step.intent.value)
            return failed(step, problem)
        return _HANDLERS[step.intent](ctx, step)
    except Exception as exc:
        if is_transient(exc):
            raise
        log.warning(
            "concierge.step_failed", company_id=str(ctx.company_id), intent=step.intent.value, error=type(exc).__name__
        )
        return failed(step, STEP_FAILED)


def run_plan(
    engine: Engine,
    settings: Settings,
    company_id: UUID,
    plan: ConciergePlan,
    *,
    question: str,
    now: datetime,
    page: PagePrompt = NO_PAGE,
    brief_cases: Collection[UUID] = (),
    turn_id: UUID | None = None,
    timer: TurnTimer | None = None,
) -> list[StepResult]:
    """`brief_cases` are the case ids of the planner's brief; with the page's case ids they are the only ones a step
    may name (none given: only the page's). `turn_id` and the step's index key an owner-requested redraft, so a
    retried turn returns the same revision (without it, a pending or decided draft is reported, not redrafted).
    The plan's `reply` (concierge/v3+) is shown by its `answer` step after screening, and only when every step is a
    read step (`concierge_reply.reply_allowed`; also guards plans stored before that rule). `timer`
    collects the owner_qa answer time (`answer_ms`)."""
    if not plan.in_scope:
        log.info("concierge.refused", company_id=str(company_id))
        return [StepResult(Intent.answer, False, REFUSAL_ANSWER, None, None)]
    ctx = Ctx(
        engine=engine, settings=settings, company_id=company_id, now=now, question=question, page=page,
        known_cases=known_case_ids(brief_cases, page), turn_id=turn_id,
        reply=plan.reply if reply_allowed(plan) else None, timer=timer or TurnTimer(),
    )  # fmt: skip
    return [_run_step(replace(ctx, step_index=i), step) for i, step in enumerate(plan.steps[:MAX_STEPS])]

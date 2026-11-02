"""Finance workflows (spec 2026-10-31, Flow): `fin:snap:{action_id}`, `fin:quote:{message_id}`,
`fin:recheck:{quote_id}:{n}` on the `finance` queue, each a thin sequence of steps over `app.finance`.

Bodies are deterministic: the clock (`today`, UTC), the database and the model live in steps. Transient DB and model
errors are retried by the step; a permanent EstateOS error (no price source configured, an unreadable model answer,
an action that is no request_contractor) is logged once by type and the run ends without a result.
The hooks (approval of a request_contractor, an inbound contractor quote) run inside other workflows and never fail
them: a hook or enqueue failure is logged, never raised. The stranded-work sweep does not cover finance in v1.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from dbos import DBOS, SetWorkflowID
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.core.settings import get_settings
from app.core.workflow_names import (
    FINANCE_QUOTE,
    FINANCE_RECHECK,
    FINANCE_SNAPSHOT,
    finance_quote_workflow_id,
    finance_recheck_workflow_id,
    finance_review_id,
    finance_snapshot_workflow_id,
)
from app.finance.quotes import recheck_quote, review_message
from app.finance.snapshot import load_request, take_snapshot
from app.finance.sources import build_price_source
from app.finance.triggers import is_quote_candidate, snapshot_company
from app.workflows import queues
from app.workflows.deps import get_engine
from app.workflows.retry import STEP_RETRY, retryable

log = get_logger(__name__)


def _today() -> date:
    return datetime.now(UTC).date()  # called inside steps only


def _permanent(event: str, exc: EstateOSError, **ids: str) -> None:
    log.warning(event, reason=type(exc).__name__, **ids)  # the type only: a message may quote untrusted text


@DBOS.step(name="finance.snapshot_target", **STEP_RETRY)
def snapshot_target_step(action_id: str) -> list[str] | None:
    """[company_id, vendor_id] of the approved request_contractor action, read from the DB; None if not applicable."""
    try:
        with Session(get_engine()) as session:
            req = load_request(session, UUID(action_id))
    except EstateOSError as exc:
        if retryable(exc):
            raise
        _permanent("finance.snapshot.not_applicable", exc, action_id=action_id)
        return None
    return [str(req.company_id), str(req.vendor_id)]


@DBOS.step(name="finance.snapshot", **STEP_RETRY)
def snapshot_step(action_id: str, company_id: str, vendor_id: str) -> int | None:
    """Rows written (or already there on a replay). The market excludes the action's own contractor."""
    engine, settings = get_engine(), get_settings()
    try:
        source = build_price_source(settings, sessionmaker(engine), UUID(company_id), UUID(vendor_id))
        outcome = take_snapshot(engine, settings, source, UUID(action_id), today=_today())
    except EstateOSError as exc:
        if retryable(exc):
            raise
        _permanent("finance.snapshot.failed", exc, action_id=action_id)
        return None
    return len(outcome.written)


@DBOS.step(name="finance.quote", **STEP_RETRY)
def quote_step(message_id: str) -> str | None:
    """The review id (new or, on a replay, the first); None: no quote, unlinked, or a permanent failure."""
    try:
        review_id = review_message(get_engine(), get_settings(), UUID(message_id), today=_today())
    except EstateOSError as exc:
        if retryable(exc):
            raise
        _permanent("finance.quote.failed", exc, message_id=message_id)
        return None
    return str(review_id) if review_id is not None else None


@DBOS.step(name="finance.recheck", **STEP_RETRY)
def recheck_step(quote_id: str, company_id: str, n: int) -> str | None:
    """The n-th recheck under a deterministic review id, so a retried step never appends a second review."""
    review_id = finance_review_id(quote_id, n)
    try:
        done = recheck_quote(
            get_engine(), get_settings(), None, UUID(quote_id), company_id=UUID(company_id), today=_today(),
            review_id=review_id,
        )  # fmt: skip
    except EstateOSError as exc:
        if retryable(exc):
            raise
        _permanent("finance.recheck.failed", exc, quote_id=quote_id)
        return None
    return str(done) if done is not None else None


@DBOS.workflow(name=FINANCE_SNAPSHOT)
def snapshot_wf(action_id: str) -> int | None:
    target = snapshot_target_step(action_id)
    if target is None:
        return None
    return snapshot_step(action_id, *target)


@DBOS.workflow(name=FINANCE_QUOTE)
def quote_wf(message_id: str) -> str | None:
    return quote_step(message_id)


@DBOS.workflow(name=FINANCE_RECHECK)
def recheck_wf(quote_id: str, company_id: str, n: int) -> str | None:
    return recheck_step(quote_id, company_id, n)


def _enqueue(workflow_id: str, company_id: str, wf: Callable[..., Any], *args: Any) -> bool:
    """Enqueue once under `workflow_id` (DBOS dedupes a repeat); a failure is logged by type and never raised."""
    try:
        with SetWorkflowID(workflow_id):
            queues.finance_queue().enqueue(wf, *args)
    except Exception as exc:
        log.error("finance.enqueue_failed", workflow_id=workflow_id, company_id=company_id, reason=type(exc).__name__)
        return False
    return True


def enqueue_snapshot(company_id: str, action_id: str) -> bool:
    return _enqueue(finance_snapshot_workflow_id(action_id), company_id, snapshot_wf, action_id)


def enqueue_quote(company_id: str, message_id: str) -> bool:
    return _enqueue(finance_quote_workflow_id(message_id), company_id, quote_wf, message_id)


def enqueue_recheck(company_id: str, quote_id: str, n: int) -> bool:
    return _enqueue(finance_recheck_workflow_id(quote_id, n), company_id, recheck_wf, quote_id, company_id, n)


@DBOS.step(name="finance.snapshot_trigger", **STEP_RETRY)
def snapshot_trigger_step(action_id: str) -> str | None:
    """The action's company when it is a request_contractor (its approval fixes the decision day), else None."""
    with Session(get_engine()) as session:
        company_id = snapshot_company(session, UUID(action_id))
    return str(company_id) if company_id is not None else None


@DBOS.step(name="finance.quote_candidate", **STEP_RETRY)
def quote_candidate_step(message_id: str) -> bool:
    with Session(get_engine()) as session:
        return is_quote_candidate(session, UUID(message_id))


def snapshot_after_approval(action_id: str) -> None:
    """Hook for `execute_action_wf` (call from a workflow body): enqueue `fin:snap:{action_id}` for a
    request_contractor. Enqueueing happens in the body, not the step: DBOS starts no workflow from inside a step."""
    try:
        company_id = snapshot_trigger_step(action_id)
    except Exception as exc:
        log.error("finance.snapshot_hook_failed", action_id=action_id, reason=type(exc).__name__)
        return
    if company_id is not None:
        enqueue_snapshot(company_id, action_id)


def quote_after_understanding(company_id: str, message_id: str) -> None:
    """Hook for the pipeline (call from a workflow body): enqueue `fin:quote:{message_id}` for a quote candidate."""
    try:
        wanted = quote_candidate_step(message_id)
    except Exception as exc:
        log.error("finance.quote_hook_failed", message_id=message_id, reason=type(exc).__name__)
        return
    if wanted:
        enqueue_quote(company_id, message_id)

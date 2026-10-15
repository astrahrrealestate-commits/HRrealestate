"""Dashboard writes: approval decisions and edits, task done/snooze, document filing, company pause/resume.

Every write commits first and enqueues after (invariant 1). Foreign ids answer the same 404 as missing ones.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.schemas import (
    DecideIn,
    DecisionOut,
    EditIn,
    FileDocumentIn,
    PausedOut,
    RevisionOut,
    SnoozeIn,
)
from app.contracts import DocType
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.db.models import ActionRow, AttachmentRow, Company
from app.pipeline import approvals, dashboard_decisions, owner_commands, work_repo
from app.pipeline.local_actions import LOCAL_TYPES

router = APIRouter(tags=["decisions"], dependencies=[Depends(require_csrf)])
log = get_logger(__name__)
NOT_FOUND = "not found"
SKIP = "skip"
DOC_CHOICES = frozenset({t.value for t in DocType} | {SKIP})
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Client = Annotated[WorkflowClient, Depends(get_workflow_client)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND)


def _is_local(session: Session, company_id: UUID, action_id: UUID) -> bool:
    action_type = session.scalar(
        select(ActionRow.type).where(ActionRow.company_id == company_id, ActionRow.id == action_id)
    )
    return action_type in LOCAL_TYPES


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: UUID, body: DecideIn, who: Owner, engine: Engine_, client: Client) -> DecisionOut:
    try:
        with Session(engine) as session, session.begin():
            d = dashboard_decisions.decide_approval(
                session,
                who.company_id,
                approval_id,
                body.choice,
                at=datetime.now(UTC),
                confirm_suspicious=body.confirm_suspicious,
            )
            local = _is_local(session, who.company_id, d.action_id)
    except NotFoundError:
        raise _not_found() from None
    except dashboard_decisions.SuspiciousNeedsConfirmError:
        raise HTTPException(status_code=409, detail="confirm_suspicious_required") from None
    if d.kind == "execute":  # after commit; a replayed decision re-sends the same id, which DBOS dedupes
        enqueue.enqueue_execute(client, d.action_id, d.draft_version, local)
    return DecisionOut(
        kind=d.kind, stale=d.kind == "stale", action_id=d.action_id, draft_version=d.draft_version, variant=d.variant
    )


@router.post("/approvals/{approval_id}/edit")
def edit(approval_id: UUID, body: EditIn, who: Owner, engine: Engine_) -> RevisionOut:
    try:
        with Session(engine) as session, session.begin():
            rev = dashboard_decisions.edit_approval(
                session, who.company_id, approval_id, body.text, at=datetime.now(UTC)
            )
    except NotFoundError:
        raise _not_found() from None
    except dashboard_decisions.NotEditableError:
        raise HTTPException(status_code=409, detail="approval_not_editable") from None
    return RevisionOut(action_id=rev.action_id, draft_version=rev.draft_version, approval_id=rev.approval_id)


@router.post("/tasks/{ref}/done", status_code=204)
def task_done(ref: str, who: Owner, engine: Engine_) -> None:
    try:
        with Session(engine) as session, session.begin():
            task_id = work_repo.resolve_task(session, who.company_id, ref)
            work_repo.complete_task(session, who.company_id, task_id, at=datetime.now(UTC))
    except NotFoundError:
        raise _not_found() from None


@router.post("/tasks/{ref}/snooze", status_code=204)
def task_snooze(ref: str, body: SnoozeIn, who: Owner, engine: Engine_) -> None:
    try:
        delta = owner_commands.parse_duration(body.duration)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    try:
        with Session(engine) as session, session.begin():
            task_id = work_repo.resolve_task(session, who.company_id, ref)
            work_repo.snooze_task(session, who.company_id, task_id, until=datetime.now(UTC) + delta)
    except NotFoundError:
        raise _not_found() from None


@router.post("/documents/{attachment_id}/file", status_code=202)
def file_document(attachment_id: UUID, body: FileDocumentIn, who: Owner, engine: Engine_, client: Client) -> None:
    if body.choice not in DOC_CHOICES:
        raise HTTPException(status_code=422, detail="unknown document choice")
    with Session(engine) as session:
        known = session.scalar(
            select(AttachmentRow.id).where(
                AttachmentRow.company_id == who.company_id, AttachmentRow.id == attachment_id
            )
        )
    if known is None:
        raise _not_found()
    enqueue.enqueue_filing(client, who.company_id, attachment_id, body.choice)


def _set_paused(engine: Engine, company_id: UUID, paused: bool) -> bool:
    """Flip the flag in one statement; returns whether it changed."""
    with Session(engine) as session, session.begin():
        changed = session.execute(
            update(Company).where(Company.id == company_id, Company.paused.is_(not paused)).values(paused=paused)
        )
    return bool(changed.rowcount)  # type: ignore[attr-defined]  # CursorResult from a DML statement


@router.post("/company/pause")
def pause(who: Owner, engine: Engine_) -> PausedOut:
    if _set_paused(engine, who.company_id, True):
        log.info("dashboard.company_paused", company_id=str(who.company_id))
    return PausedOut(paused=True)


@router.post("/company/resume")
def resume(who: Owner, engine: Engine_, client: Client) -> PausedOut:
    changed = _set_paused(engine, who.company_id, False)
    if changed:
        log.info("dashboard.company_resumed", company_id=str(who.company_id))
        request_id = uuid4().hex
        with Session(engine) as session:
            pending = approvals.approved_unexecuted(session, who.company_id)
        for action_id, version, action_type in pending:
            enqueue.enqueue_execute(
                client, action_id, version, action_type in LOCAL_TYPES, suffix=f"resume:{request_id}"
            )
    return PausedOut(paused=False)

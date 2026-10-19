"""Tasks, waits, briefing and company settings. Read-only."""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import BriefingOut, CompanyOut, TaskOut, WaitOut
from app.pipeline import briefing, work_repo
from app.pipeline.read_work import get_company, open_waits

router = APIRouter(tags=["work"])


def _read_tasks(engine: Engine, company_id: UUID, now: datetime) -> list[TaskOut]:
    with Session(engine) as session:
        tasks = work_repo.open_tasks(session, company_id, now=now)
        return [
            TaskOut(
                id=t.id,
                ref=work_repo.short_ref(t.id),
                title=t.title,
                assignee=t.assignee,
                due_at=t.due_at,
                priority=t.priority,
                status=t.status,
                case_id=t.case_id,
            )
            for t in tasks
        ]


def _read_waits(engine: Engine, company_id: UUID) -> list[WaitOut]:
    with Session(engine) as session:
        return [WaitOut.model_validate(w, from_attributes=True) for w in open_waits(session, company_id)]


def _read_company(engine: Engine, company_id: UUID) -> CompanyOut:
    with Session(engine) as session:
        return CompanyOut.model_validate(get_company(session, company_id), from_attributes=True)


@router.get("/tasks")
async def get_tasks(request: Request, principal: Annotated[Principal, Depends(require_principal)]) -> list[TaskOut]:
    return await run_in_threadpool(_read_tasks, request.app.state.engine, principal.company_id, datetime.now(UTC))


@router.get("/waits")
async def get_waits(request: Request, principal: Annotated[Principal, Depends(require_principal)]) -> list[WaitOut]:
    return await run_in_threadpool(_read_waits, request.app.state.engine, principal.company_id)


@router.get("/briefing")
async def get_briefing(request: Request, principal: Annotated[Principal, Depends(require_principal)]) -> BriefingOut:
    facts = await run_in_threadpool(
        briefing.collect, request.app.state.engine, principal.company_id, "daily", datetime.now(UTC)
    )
    return BriefingOut(**asdict(facts))


@router.get("/company")
async def get_company_settings(
    request: Request, principal: Annotated[Principal, Depends(require_principal)]
) -> CompanyOut:
    return await run_in_threadpool(_read_company, request.app.state.engine, principal.company_id)

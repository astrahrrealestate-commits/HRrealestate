"""Case list and detail, plus the activity log. Read-only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import (
    ActionOut,
    ActivityItem,
    ApprovalOut,
    CaseDetail,
    CaseEventOut,
    CaseSummary,
)
from app.contracts import CaseState
from app.core.errors import NotFoundError
from app.pipeline.read_cases import ActivityRow, CaseBundle, activity, case_bundle, list_cases
from app.pipeline.read_repo import MAX_PAGE

router = APIRouter(
    tags=["cases"], dependencies=[Depends(require_section("inbox", also=("maintenance",), also_read=("dashboard",)))]
)
NOT_FOUND = "case not found"  # same body for a missing and a foreign id


def _read_cases(engine: Engine, company_id: UUID, state: CaseState | None, limit: int) -> list[CaseSummary]:
    with Session(engine) as session:
        cases = list_cases(session, company_id, state, limit)
        return [CaseSummary.model_validate(c, from_attributes=True) for c in cases]


def _detail(b: CaseBundle) -> CaseDetail:
    summary = CaseSummary.model_validate(b.case, from_attributes=True)
    return CaseDetail(
        **summary.model_dump(),
        timeline=[CaseEventOut.model_validate(e, from_attributes=True) for e in b.timeline],
        message_ids=b.message_ids,
        actions=[
            ActionOut(
                id=a.id,
                type=a.type,
                status=a.status,
                draft_version=a.draft_version,
                rationale=a.rationale,
                payload=a.payload,
                approval=ApprovalOut.model_validate(ap, from_attributes=True) if ap else None,
            )
            for a, ap in b.actions
        ],
    )


def _read_case(engine: Engine, company_id: UUID, case_id: UUID) -> CaseDetail:
    with Session(engine) as session:
        return _detail(case_bundle(session, company_id, case_id))


def _read_activity(engine: Engine, company_id: UUID, limit: int) -> list[ActivityItem]:
    with Session(engine) as session:
        rows: list[ActivityRow] = activity(session, company_id, limit)
    return [ActivityItem(**r.__dict__) for r in rows]


@router.get("/cases")
async def get_cases(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    state: CaseState | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[CaseSummary]:
    return await run_in_threadpool(_read_cases, request.app.state.engine, principal.company_id, state, limit)


@router.get("/cases/{case_id}")
async def get_case(
    request: Request, case_id: UUID, principal: Annotated[Principal, Depends(require_principal)]
) -> CaseDetail:
    try:
        return await run_in_threadpool(_read_case, request.app.state.engine, principal.company_id, case_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=NOT_FOUND) from None


@router.get("/activity")
async def get_activity(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[ActivityItem]:
    return await run_in_threadpool(_read_activity, request.app.state.engine, principal.company_id, limit)

"""What waits for Harjot's click: pending approvals and documents to file. Read-only, cursor-paged, company-scoped."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal, require_principal
from app.api.v1.schemas import PendingApprovalOut, ReviewDocumentOut
from app.pipeline.read_approvals import pending_approvals, review_documents
from app.pipeline.read_repo import MAX_PAGE, BadCursorError, parse_cursor

router = APIRouter(tags=["reviews"])


def _read_approvals(engine: Engine, company_id: UUID, after: str | None, limit: int) -> list[PendingApprovalOut]:
    cursor = parse_cursor(after) if after else None
    with Session(engine) as session:
        rows = pending_approvals(session, company_id, cursor, limit)
    return [
        PendingApprovalOut(
            id=r.id,
            cursor=f"{r.created_at.isoformat()}|{r.id}",
            action_id=r.action_id,
            action_type=r.action_type,
            case_id=r.case_id,
            case_label=r.case_label,
            drafts=list(r.drafts),
            draft_version=r.draft_version,
            suspicious=r.suspicious,
            created_at=r.created_at,
        )
        for r in rows
    ]


def _read_documents(engine: Engine, company_id: UUID, after: str | None, limit: int) -> list[ReviewDocumentOut]:
    cursor = parse_cursor(after) if after else None
    with Session(engine) as session:
        rows = review_documents(session, company_id, cursor, limit)
    return [
        ReviewDocumentOut(
            attachment_id=r.attachment_id,
            cursor=f"{r.created_at.isoformat()}|{r.id}",
            filename=r.filename,
            mime_type=r.mime_type,
            case_id=r.case_id,
            suggested_type=r.suggested_type,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/approvals")
async def get_approvals(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[PendingApprovalOut]:
    try:
        return await run_in_threadpool(_read_approvals, request.app.state.engine, principal.company_id, after, limit)
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None


@router.get("/documents/review")
async def get_documents_to_review(
    request: Request,
    principal: Annotated[Principal, Depends(require_principal)],
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> list[ReviewDocumentOut]:
    try:
        return await run_in_threadpool(_read_documents, request.app.state.engine, principal.company_id, after, limit)
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None

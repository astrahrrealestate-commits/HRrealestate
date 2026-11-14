"""Quote checker, owner surface: the company's quotes with their latest review, one quote with its stored report,
and a recheck. Read routes are company-scoped through the session principal; foreign ids answer the same 404 as
missing ones. The recheck commits nothing itself: it enqueues `fin:recheck:{quote_id}:{n}` by name (invariant 1: the
quote and its reviews are already rows) and the worker appends the review and its feed card.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.v1 import enqueue
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.finance_schemas import QuoteDetailOut, QuoteOut, RecheckOut, detail_out, quote_out
from app.api.v1.ratelimit import decision_limit
from app.core.logging import get_logger
from app.finance import repo_read
from app.pipeline.read_repo import BadCursorError, parse_cursor

router = APIRouter(tags=["finance"], dependencies=[Depends(require_section("money"))])
log = get_logger(__name__)
NOT_FOUND = "not found"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
Client = Annotated[WorkflowClient, Depends(get_workflow_client)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=NOT_FOUND)


@router.get("/finance/quotes")
def list_quotes(
    who: Owner,
    engine: Engine_,
    case_id: UUID | None = None,
    person_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[QuoteOut]:
    try:
        before = parse_cursor(cursor) if cursor else None
    except BadCursorError:
        raise HTTPException(status_code=422, detail="invalid cursor") from None
    with Session(engine) as session:
        rows = repo_read.list_quotes(
            session, who.company_id, case_id=case_id, person_id=person_id, before=before, limit=limit
        )
    return [quote_out(r) for r in rows]


@router.get("/finance/quotes/{quote_id}")
def read_quote(quote_id: UUID, who: Owner, engine: Engine_) -> QuoteDetailOut:
    with Session(engine) as session:
        found = repo_read.get_quote(session, who.company_id, quote_id)
    if found is None:
        raise _not_found()
    return detail_out(found)


@router.post(
    "/finance/quotes/{quote_id}/recheck", status_code=202, dependencies=[Depends(require_csrf), Depends(decision_limit)]
)
def recheck(quote_id: UUID, who: Owner, engine: Engine_, client: Client) -> RecheckOut:
    """Review the stored quote again with fresh prices. `n` = reviews stored so far, so clicking again before the
    worker finishes is the same workflow id (deduped); after it finishes the next click is the next `n`."""
    with Session(engine) as session:
        found = repo_read.get_quote(session, who.company_id, quote_id)
        if found is None:
            raise _not_found()
        if found.quote.person_id is None:
            raise HTTPException(status_code=409, detail="quote_not_linked")
        n = repo_read.review_count(session, who.company_id, quote_id)
    enqueue.enqueue_finance_recheck(client, quote_id, who.company_id, n)
    return RecheckOut(quote_id=quote_id, n=n)

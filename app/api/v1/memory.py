"""Dashboard API: manage T5 preferences and standing rules (spec §6.2, Task C11).

Endpoints to list, record, update, approve/reject, and retire company memory items.
Every operation is strictly company-scoped (invariant 4).
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.schemas import CreateMemoryIn, MemoryItemOut, UpdateMemoryIn
from app.context import memory_items
from app.core.logging import get_logger
from app.db.enums import FeedKind, MemoryKind, MemoryScope, MemoryStatus
from app.db.models import OwnerFeed

router = APIRouter(prefix="/memory", tags=["memory"])
log = get_logger(__name__)
NOT_FOUND = "not found"

Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]


def _resolve_feed_review(session: Session, company_id: UUID, memory_id: UUID) -> None:
    session.execute(
        update(OwnerFeed)
        .where(
            OwnerFeed.company_id == company_id,
            OwnerFeed.kind == FeedKind.memory_review,
            OwnerFeed.ref_id == memory_id,
            OwnerFeed.resolved_at.is_(None),
        )
        .values(resolved_at=datetime.now(tz=UTC))
    )


@router.get("", response_model=list[MemoryItemOut])
def list_memories(
    who: Owner,
    engine: Engine_,
    status_filter: Annotated[MemoryStatus | None, Query(alias="status")] = None,
    scope: Annotated[MemoryScope | None, Query()] = None,
    kind: Annotated[MemoryKind | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MemoryItemOut]:
    with Session(engine) as session:
        items = memory_items.list_memory_items(
            session,
            who.company_id,
            status=status_filter,
            scope=scope,
            kind=kind,
            limit=limit,
        )
        return [MemoryItemOut.model_validate(it) for it in items]


@router.post(
    "",
    response_model=MemoryItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_memory(
    body: CreateMemoryIn,
    who: Owner,
    engine: Engine_,
) -> MemoryItemOut:
    with Session(engine) as session, session.begin():
        item, reason = memory_items.record_owner_memory(
            session,
            who.company_id,
            body.text,
            scope=body.scope,
            scope_id=body.scope_id,
            kind=body.kind,
        )
        if item is None:
            raise HTTPException(status_code=422, detail=reason)
        return MemoryItemOut.model_validate(item)


@router.get("/{memory_id}", response_model=MemoryItemOut)
def get_memory(
    memory_id: UUID,
    who: Owner,
    engine: Engine_,
) -> MemoryItemOut:
    with Session(engine) as session:
        item = memory_items.get_memory_item(session, who.company_id, memory_id)
        if item is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        return MemoryItemOut.model_validate(item)


@router.patch("/{memory_id}", response_model=MemoryItemOut, dependencies=[Depends(require_csrf)])
def update_memory(
    memory_id: UUID,
    body: UpdateMemoryIn,
    who: Owner,
    engine: Engine_,
) -> MemoryItemOut:
    with Session(engine) as session, session.begin():
        item, error = memory_items.update_memory_item(
            session,
            who.company_id,
            memory_id,
            text=body.text,
            status=body.status,
            scope=body.scope,
            scope_id=body.scope_id,
            kind=body.kind,
        )
        if error == "Not found" or item is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        if error is not None:
            raise HTTPException(status_code=422, detail=error)
        if body.status in (MemoryStatus.active, MemoryStatus.retired):
            _resolve_feed_review(session, who.company_id, memory_id)
        return MemoryItemOut.model_validate(item)


@router.post("/{memory_id}/approve", response_model=MemoryItemOut, dependencies=[Depends(require_csrf)])
def approve_memory(
    memory_id: UUID,
    who: Owner,
    engine: Engine_,
) -> MemoryItemOut:
    with Session(engine) as session, session.begin():
        item, error = memory_items.update_memory_item(
            session,
            who.company_id,
            memory_id,
            status=MemoryStatus.active,
        )
        if error == "Not found" or item is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        _resolve_feed_review(session, who.company_id, memory_id)
        return MemoryItemOut.model_validate(item)


@router.post("/{memory_id}/reject", response_model=MemoryItemOut, dependencies=[Depends(require_csrf)])
def reject_memory(
    memory_id: UUID,
    who: Owner,
    engine: Engine_,
) -> MemoryItemOut:
    with Session(engine) as session, session.begin():
        item, error = memory_items.update_memory_item(
            session,
            who.company_id,
            memory_id,
            status=MemoryStatus.retired,
        )
        if error == "Not found" or item is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        _resolve_feed_review(session, who.company_id, memory_id)
        return MemoryItemOut.model_validate(item)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def delete_memory(
    memory_id: UUID,
    who: Owner,
    engine: Engine_,
) -> None:
    with Session(engine) as session, session.begin():
        ok = memory_items.retire_memory(session, who.company_id, memory_id)
        if not ok:
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        _resolve_feed_review(session, who.company_id, memory_id)

"""Category desk API routes (M13 T10): summary counts and ranked next actions per business category."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.dashboard.attention import Viewer, attention_items
from app.api.deps import get_engine
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import Category
from app.directory.brixx.sync import BRIXX_TZ
from app.pipeline.next_actions import (
    ActionViewer,
    BrixxAttentionLike,
    CategorySummary,
    NextAction,
    category_brief,
    category_summaries,
    next_actions,
)

ShownCategory = Literal["maintenance", "finance", "legal", "business", "administration", "new_projects"]

router = APIRouter(
    prefix="/api/dashboard/categories",
    tags=["dashboard"],
    dependencies=[Depends(require_section("dashboard"))],
)


class CategoryDeskResponse(BaseModel):
    brief: str | None
    actions: list[NextAction]


def _today() -> date:
    return datetime.now(UTC).astimezone(BRIXX_TZ).date()


def _brixx(session: Session, principal: Principal) -> tuple[ActionViewer, list[BrixxAttentionLike]]:
    v = Viewer(money=principal.access.can("money"), inbox=principal.access.can("inbox"))
    raw = attention_items(session, principal.company_id, _today(), v)
    adapted = [
        BrixxAttentionLike(
            id=i.id,
            kind=i.kind,
            title=i.title,
            detail=i.detail,
            unit_label=i.unitLabel,
            party_name=i.partyName,
            urgent=i.urgent,
            age_days=i.ageDays,
            href=i.href,
        )
        for i in raw
    ]
    return ActionViewer(money=v.money, inbox=v.inbox), adapted


@router.get("", response_model=list[CategorySummary], summary="List business categories with open/urgent counts")
def list_categories(
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> list[CategorySummary]:
    with Session(engine) as session:
        viewer, brixx = _brixx(session, principal)
        return category_summaries(session, principal.company_id, viewer, brixx_items=brixx)


@router.get("/{category}", response_model=CategoryDeskResponse, summary="Get brief and next actions for a category")
def get_category_desk(
    category: ShownCategory,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
    limit: int = Query(default=15, ge=1, le=50),
) -> CategoryDeskResponse:
    with Session(engine) as session:
        viewer, brixx = _brixx(session, principal)
        actions = next_actions(
            session, principal.company_id, Category(category), viewer, limit=limit, brixx_items=brixx
        )
    return CategoryDeskResponse(brief=category_brief(actions), actions=actions)

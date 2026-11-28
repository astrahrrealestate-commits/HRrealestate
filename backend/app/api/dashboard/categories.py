"""Category desk API routes (M13 T10): summary counts and ranked next actions per business category."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.dashboard.attention import Viewer, attention_items
from app.api.deps import get_engine, get_settings_dep
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.contracts import CaseState, Category
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.directory.brixx.sync import BRIXX_TZ
from app.pipeline import case_repo, followups, work_repo
from app.pipeline.next_actions import (
    ActionViewer,
    BrixxAttentionLike,
    CategorySummary,
    NextAction,
    action_periods,
    category_brief,
    category_summaries,
    enrich_actions,
    latest_sort_ts,
    matches_period,
    ranked_actions,
    waiting_split_page,
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
    total: int = 0
    has_more: bool = False
    emergency_count: int = 0
    urgent_count: int = 0
    low_count: int = 0
    waiting_for_us: list[NextAction] = Field(default_factory=list)
    waiting_for_other: list[NextAction] = Field(default_factory=list)
    waiting_for_us_total: int = 0
    waiting_for_other_total: int = 0
    available_periods: list[str] = Field(default_factory=list)


def _today() -> date:
    return datetime.now(UTC).astimezone(BRIXX_TZ).date()


def _viewer(principal: Principal) -> ActionViewer:
    return ActionViewer(money=principal.access.can("money"), inbox=principal.access.can("inbox"))


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
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    urgency: Literal["all", "emergency", "high", "low", "urgent"] = Query(default="all"),
    sort: Literal["priority", "latest"] = Query(default="priority"),
    period: str = Query(default="all"),
    radar_limit: int = Query(default=15, ge=1, le=200),
) -> CategoryDeskResponse:
    now = datetime.now(UTC)
    with Session(engine) as session:
        viewer, brixx = _brixx(session, principal)
        cat = Category(category)
        all_cat = ranked_actions(session, principal.company_id, cat, viewer, brixx_items=brixx, urgency_filter="all")
        periods = action_periods(all_cat)
        in_period = [a for a in all_cat if matches_period(a, period, now)] if period != "all" else all_cat
        if urgency == "emergency":
            ranked = [a for a in in_period if a.urgency.value == "emergency"]
        elif urgency == "high":
            ranked = [a for a in in_period if a.urgency.value == "high"]
        elif urgency == "low":
            ranked = [a for a in in_period if a.urgency.value in ("normal", "low")]
        elif urgency == "urgent":
            ranked = [a for a in in_period if a.urgency.value in ("emergency", "high")]
        else:
            ranked = in_period
        if sort == "latest":
            ranked = sorted(ranked, key=latest_sort_ts, reverse=True)
        page = ranked[offset : offset + limit]
        actions = enrich_actions(session, principal.company_id, viewer, page, now=now)
        wait_us, wait_other, wait_us_total, wait_other_total = waiting_split_page(
            session,
            principal.company_id,
            cat,
            viewer,
            now=now,
            limit=radar_limit,
            urgency_filter=urgency,
            sort=sort,
            period=period,
        )
    total_matching = len(ranked)
    return CategoryDeskResponse(
        brief=category_brief(all_cat),  # every action of the category, not only the page shown
        actions=actions,
        total=total_matching,
        has_more=(offset + len(actions)) < total_matching,
        emergency_count=sum(1 for a in in_period if a.urgency.value == "emergency"),
        urgent_count=sum(1 for a in in_period if a.urgency.value == "high"),
        low_count=sum(1 for a in in_period if a.urgency.value in ("normal", "low")),
        waiting_for_us=wait_us,
        waiting_for_other=wait_other,
        waiting_for_us_total=wait_us_total,
        waiting_for_other_total=wait_other_total,
        available_periods=periods,
    )


@router.post(
    "/followups/{case_id}/chase",
    summary="Generate or return a pending chaser draft for a follow-up case",
    dependencies=[Depends(require_section("inbox"))],
)
def chase_followup_case(
    case_id: UUID,
    engine: Annotated[Engine, Depends(get_engine)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, str | None]:
    try:
        approval_id = followups.ensure_case_chaser_draft(
            engine, settings, principal.company_id, case_id, now=datetime.now(UTC)
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Case not found") from None
    return {"approval_id": str(approval_id) if approval_id is not None else None}


@router.post(
    "/followups/{case_id}/resolve",
    summary="Mark a follow-up or commitment resolved",
    dependencies=[Depends(require_section("inbox"))],
)
def resolve_followup_case(
    case_id: UUID,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> dict[str, bool]:
    try:
        with Session(engine) as session, session.begin():
            case = case_repo.get_case(session, principal.company_id, case_id)
            work_repo.resolve_case_waits(session, principal.company_id, case_id)
            work_repo.close_case_tasks(session, principal.company_id, case_id, source="promise")
            work_repo.close_case_tasks(session, principal.company_id, case_id, source="reminder")
            case_repo.expire_pending_reply_drafts(session, principal.company_id, case_id)
            if case.state in (CaseState.open, CaseState.waiting_on_owner, CaseState.waiting_on_third_party):
                case_repo.transition(session, principal.company_id, case_id, CaseState.resolved, actor="owner")
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Case not found") from None
    return {"resolved": True}

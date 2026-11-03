"""Owner rate cards (what a contractor agreed to charge): list, set (upsert) and remove.

A rate is unique per (contractor, item_key, valid_from): setting it again updates that row. Removing a rate that a
price snapshot references closes it instead (snapshots are immutable decision-day facts). EUR only.
"""

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.api.v1.auth import Principal, require_csrf, require_principal
from app.api.v1.finance_schemas import RateIn, RateOut, RateRemovedOut
from app.api.v1.ratelimit import decision_limit
from app.core.property_terms import normalise_unit
from app.db.enums import RateSource
from app.db.models import VendorRate
from app.finance import repo
from app.pipeline.read_work import get_company

router = APIRouter(tags=["finance"])
NOT_FOUND = "not found"
Owner = Annotated[Principal, Depends(require_principal)]
Engine_ = Annotated[Engine, Depends(get_engine)]
WRITE = [Depends(require_csrf), Depends(decision_limit)]


def _today(session: Session, company_id: UUID) -> date:
    return datetime.now(UTC).astimezone(ZoneInfo(get_company(session, company_id).timezone)).date()


@router.get("/finance/rates")
def list_rates(
    who: Owner, engine: Engine_, person_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 200
) -> list[RateOut]:
    with Session(engine) as session:
        rows = repo.list_rates(session, who.company_id, person_id=person_id, limit=limit)
        return [RateOut.model_validate(r, from_attributes=True) for r in rows]


@router.put("/finance/rates", dependencies=WRITE)
def put_rate(body: RateIn, who: Owner, engine: Engine_) -> RateOut:
    with Session(engine) as session, session.begin():
        if not repo.is_contractor(session, who.company_id, body.person_id):
            raise HTTPException(status_code=404, detail=NOT_FOUND)
        start = body.valid_from or _today(session, who.company_id)
        if body.valid_to is not None and body.valid_to < start:
            raise HTTPException(status_code=422, detail="valid_to must be on or after valid_from")
        rate: VendorRate = repo.upsert_rate(
            session, who.company_id, person_id=body.person_id, item_key=body.resolved_item_key(),
            description=body.description, unit=normalise_unit(body.unit), amount=body.amount,
            currency=body.currency, valid_from=start, valid_to=body.valid_to, source=RateSource.owner,
        )  # fmt: skip
        return RateOut.model_validate(rate, from_attributes=True)


@router.delete("/finance/rates/{rate_id}", dependencies=WRITE)
def delete_rate(rate_id: UUID, who: Owner, engine: Engine_) -> RateRemovedOut:
    """200 either way: `action` says whether the row was `deleted` or only `closed` (valid_to = today)."""
    with Session(engine) as session, session.begin():
        done = repo.remove_rate(session, who.company_id, rate_id, today=_today(session, who.company_id))
    if done is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    action, valid_to = done
    return RateRemovedOut(id=rate_id, action=action, valid_to=valid_to)

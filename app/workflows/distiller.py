"""Nightly memory distiller workflow (spec §6.3, Task C11).

Runs nightly to distill candidate preferences from owner draft revisions
and retire memories unused for >= 180 days.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Company
from app.pipeline.distiller import distill_company
from app.workflows.deps import get_engine

log = get_logger(__name__)


@DBOS.step(name="distiller.companies")
def companies_step() -> list[str]:
    with Session(get_engine()) as session:
        ids = session.scalars(select(Company.id)).all()
    return [str(cid) for cid in ids]


@DBOS.step(name="distiller.company")
def distill_company_step(company_id: str, now_iso: str) -> dict[str, int]:
    now = datetime.fromisoformat(now_iso)
    with Session(get_engine()) as session, session.begin():
        proposed, retired = distill_company(session, UUID(company_id), now)
    log.info("distiller.company.done", company_id=company_id, proposed=proposed, retired=retired)
    return {"proposed": proposed, "retired": retired}


@DBOS.workflow(name="distiller.nightly")
def distiller_cron(scheduled_time: datetime, context: Any) -> None:
    now_iso = scheduled_time.astimezone(UTC).isoformat()
    for company_id in companies_step():
        try:
            distill_company_step(company_id, now_iso)
        except Exception as exc:
            log.error("distiller.company.failed", company_id=company_id, error=type(exc).__name__)

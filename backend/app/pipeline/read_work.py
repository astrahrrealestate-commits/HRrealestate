"""Open waits and company settings for the dashboard API. Tasks and overdue waits come from `work_repo`."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.enums import WaitStatus
from app.db.models import Company, WaitRow

MAX_WAITS = 200


def open_waits(
    session: Session, company_id: UUID, *, statuses: Sequence[WaitStatus] = (WaitStatus.waiting,)
) -> list[WaitRow]:
    q = select(WaitRow).where(WaitRow.company_id == company_id, WaitRow.status.in_(statuses))
    return list(session.scalars(q.order_by(WaitRow.expected_by, WaitRow.id).limit(MAX_WAITS)))


def get_company(session: Session, company_id: UUID) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise NotFoundError(f"company {company_id} not found")
    return company

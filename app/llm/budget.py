"""Per-company LLM usage limits, checked by `run_agent` before every call.

All limits default to None (unlimited). With none configured `check_budget` runs no query. Days and months are UTC.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.errors import BudgetExceededError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import ModelCall

log = get_logger(__name__)
OWNER_QA_PURPOSE = "owner_qa"
CONCIERGE_PURPOSE = "concierge"


@dataclass(frozen=True)
class Usage:
    spend_day: Decimal
    spend_month: Decimal
    calls_day: int
    purpose_spend_day: Decimal
    purpose_calls_day: int


def _limits(settings: Settings, purpose: str, usage: Usage) -> list[tuple[str, Decimal | int | None, Decimal | int]]:
    rows: list[tuple[str, Decimal | int | None, Decimal | int]] = [
        ("daily_budget", settings.llm_daily_budget_usd, usage.spend_day),
        ("monthly_budget", settings.llm_monthly_budget_usd, usage.spend_month),
        ("daily_calls", settings.llm_daily_calls_cap, usage.calls_day),
    ]
    if purpose == OWNER_QA_PURPOSE:
        rows += [
            ("owner_qa_daily_budget", settings.owner_qa_daily_budget_usd, usage.purpose_spend_day),
            ("owner_qa_daily_calls", settings.owner_qa_daily_cap, usage.purpose_calls_day),
        ]
    if purpose == CONCIERGE_PURPOSE:
        rows += [
            ("concierge_daily_budget", settings.concierge_daily_budget_usd, usage.purpose_spend_day),
            ("concierge_daily_calls", settings.concierge_daily_cap, usage.purpose_calls_day),
        ]
    return rows


def exceeded(settings: Settings, purpose: str, usage: Usage) -> str | None:
    """Name of the first spent limit, or None."""
    for name, limit, used in _limits(settings, purpose, usage):
        if limit is not None and used >= limit:
            return name
    return None


def load_usage(engine: Engine, company_id: UUID, purpose: str, now: datetime) -> Usage:
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    today = ModelCall.created_at >= day
    mine = today & (ModelCall.purpose == purpose)
    spend = func.coalesce(func.sum(ModelCall.cost_usd), 0)
    query = select(
        func.coalesce(func.sum(ModelCall.cost_usd).filter(today), 0),
        spend,
        func.count().filter(today),
        func.coalesce(func.sum(ModelCall.cost_usd).filter(mine), 0),
        func.count().filter(mine),
    ).where(ModelCall.company_id == company_id, ModelCall.created_at >= month)
    with Session(engine) as session:
        row = session.execute(query).one()
    return Usage(Decimal(row[0] or 0), Decimal(row[1] or 0), int(row[2]), Decimal(row[3] or 0), int(row[4]))


def _any_limit(settings: Settings, purpose: str) -> bool:
    zero = Usage(Decimal(0), Decimal(0), 0, Decimal(0), 0)
    return any(limit is not None for _, limit, _ in _limits(settings, purpose, zero))


def check_budget(
    engine: Engine, settings: Settings, company_id: UUID, purpose: str, now: datetime | None = None
) -> None:
    """Raise BudgetExceededError when a configured limit is spent. No query at all when no limit is configured."""
    if not _any_limit(settings, purpose):
        return
    usage = load_usage(engine, company_id, purpose, now or datetime.now(UTC))
    scope = exceeded(settings, purpose, usage)
    if scope is not None:
        log.warning("llm.budget_blocked", company_id=str(company_id), purpose=purpose, scope=scope)
        raise BudgetExceededError(scope)

"""Drift monitor (#8): one snapshot per metric per company-day, compared with the trailing 14-day median.

Autonomy: share of drafts sent unchanged, edit/rewrite rates, rejection rate. Cost: LLM spend. Performance: LLM p95
latency and error rate, failed pipeline runs. A breach needs a baseline (at least 3 earlier days); thresholds can be
overridden per company in `companies.drift_thresholds` ({metric: amount}).
"""

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.enums import ApprovalStatus, OutcomeLabel, PipelineStatus
from app.db.models import Approval, Company, MessageRow, MetricSnapshot, ModelCall, Outcome

BASELINE_DAYS, MIN_HISTORY = 14, 3
Rule = tuple[Literal["drop", "rise"], Literal["abs", "ratio"], float]
RULES: dict[str, Rule] = {
    "autonomy_unchanged_rate": ("drop", "abs", 0.20),
    "outcome_rewrite_rate": ("rise", "abs", 0.20),
    "approval_rejection_rate": ("rise", "abs", 0.20),
    "llm_cost_usd": ("rise", "ratio", 2.0),
    "llm_error_rate": ("rise", "abs", 0.10),
    "llm_p95_latency_ms": ("rise", "ratio", 2.0),
    "pipeline_failed": ("rise", "abs", 3.0),
}


@dataclass(frozen=True)
class Breach:
    metric: str
    value: float
    baseline: float


def evaluate(metric: str, value: float, baseline: float | None, overrides: dict[str, float]) -> bool:
    if baseline is None:
        return False
    direction, mode, amount = RULES[metric]
    amount = float(overrides.get(metric, amount))
    if mode == "ratio":
        return baseline > 0 and value > baseline * amount
    return (baseline - value > amount) if direction == "drop" else (value - baseline > amount)


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _outcome_rates(session: Session, cid: UUID, start: datetime, end: datetime) -> dict[str, float | None]:
    labels = session.scalars(
        select(Outcome.label).where(Outcome.company_id == cid, Outcome.created_at >= start, Outcome.created_at < end)
    ).all()
    decided = session.scalars(
        select(Approval.status).where(
            Approval.company_id == cid, Approval.decided_at >= start, Approval.decided_at < end
        )
    ).all()
    return {
        "autonomy_unchanged_rate": _rate(labels.count(OutcomeLabel.unchanged), len(labels)),
        "outcome_rewrite_rate": _rate(labels.count(OutcomeLabel.rewritten), len(labels)),
        "approval_rejection_rate": _rate(decided.count(ApprovalStatus.rejected), len(decided)),
    }


def _llm(session: Session, cid: UUID, start: datetime, end: datetime) -> dict[str, float | None]:
    window = (ModelCall.company_id == cid, ModelCall.created_at >= start, ModelCall.created_at < end)
    total, errors, cost, p95 = session.execute(
        select(
            func.count(),
            func.count(ModelCall.error),
            func.coalesce(func.sum(ModelCall.cost_usd), 0),
            func.percentile_cont(0.95).within_group(ModelCall.latency_ms),
        ).where(*window)
    ).one()
    failed = session.scalar(
        select(func.count())
        .select_from(MessageRow)
        .where(
            MessageRow.company_id == cid,
            MessageRow.pipeline_status == PipelineStatus.failed,
            MessageRow.created_at >= start,
            MessageRow.created_at < end,
        )
    )
    return {
        "llm_cost_usd": float(cost),
        "llm_error_rate": _rate(errors, total) if total else 0.0,
        "llm_p95_latency_ms": float(p95) if p95 is not None else None,
        "pipeline_failed": float(failed or 0),
    }


def _baseline(session: Session, cid: UUID, metric: str, day: date) -> float | None:
    values = session.scalars(
        select(MetricSnapshot.value).where(
            MetricSnapshot.company_id == cid,
            MetricSnapshot.metric == metric,
            MetricSnapshot.day < day,
            MetricSnapshot.day >= day - timedelta(days=BASELINE_DAYS),
        )
    ).all()
    return statistics.median(values) if len(values) >= MIN_HISTORY else None


def run_drift(engine: Engine, company_id: UUID, day: date) -> list[Breach]:
    """Snapshot `day` (company-local) for one company and return the breaches. Re-running a day overwrites it."""
    with Session(engine) as session, session.begin():
        company = session.get(Company, company_id)
        if company is None:
            raise NotFoundError(f"company {company_id} not found")
        tz = ZoneInfo(company.timezone)
        start = datetime.combine(day, time(0), tzinfo=tz)
        end = start + timedelta(days=1)
        metrics = {**_outcome_rates(session, company_id, start, end), **_llm(session, company_id, start, end)}
        breaches: list[Breach] = []
        for metric, value in metrics.items():
            if value is None:
                continue
            base = _baseline(session, company_id, metric, day)
            breached = evaluate(metric, value, base, company.drift_thresholds)
            if breached and base is not None:
                breaches.append(Breach(metric, value, base))
            row = {
                "company_id": company_id,
                "day": day,
                "metric": metric,
                "value": value,
                "baseline": base,
                "breached": breached,
            }
            session.execute(
                insert(MetricSnapshot)
                .values(**row)
                .on_conflict_do_update(
                    index_elements=["company_id", "day", "metric"],
                    set_={"value": value, "baseline": base, "breached": breached},
                )
            )
        return breaches

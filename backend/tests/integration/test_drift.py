"""Drift monitor (#8): daily autonomy / cost / performance snapshots against a 14-day median baseline."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import Company, MetricSnapshot, ModelCall
from app.outcomes.drift import evaluate, run_drift

pytestmark = pytest.mark.integration
DAY = date(2026, 10, 6)


def _calls(engine: Engine, company: Company, n: int, cost: str, latency: int, errors: int = 0) -> None:
    at = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
    with Session(engine) as s, s.begin():
        for i in range(n):
            s.add(
                ModelCall(
                    id=new_id(),
                    company_id=company.id,
                    purpose="triage",
                    prompt_name="understanding",
                    prompt_version="v1",
                    prompt_sha256="0" * 64,
                    model="openai:x",
                    input={},
                    cost_usd=Decimal(cost),
                    latency_ms=latency,
                    error="boom" if i < errors else None,
                    created_at=at,
                )
            )


def _history(engine: Engine, company: Company, metric: str, value: float, days: int = 7) -> None:
    with Session(engine) as s, s.begin():
        for d in range(1, days + 1):
            s.add(MetricSnapshot(company_id=company.id, day=DAY - timedelta(days=d), metric=metric, value=value))


def test_cost_spike_breaches_and_snapshots_are_upserted(migrated_engine: Engine, committed_company: Company) -> None:
    _history(migrated_engine, committed_company, "llm_cost_usd", 1.0)
    _calls(migrated_engine, committed_company, 10, "0.5", 800)
    breaches = run_drift(migrated_engine, committed_company.id, DAY)
    assert [b.metric for b in breaches] == ["llm_cost_usd"]
    assert breaches[0].value == pytest.approx(5.0)
    assert breaches[0].baseline == pytest.approx(1.0)
    assert run_drift(migrated_engine, committed_company.id, DAY)  # rerun: same answer, no duplicate rows
    with Session(migrated_engine) as s:
        rows = s.scalars(
            select(MetricSnapshot).where(MetricSnapshot.company_id == committed_company.id, MetricSnapshot.day == DAY)
        ).all()
    metrics = {r.metric: r for r in rows}
    assert metrics["llm_cost_usd"].breached
    assert metrics["llm_error_rate"].value == 0.0
    assert not metrics["llm_p95_latency_ms"].breached  # no history yet: no baseline, no breach


def test_error_rate_rise_and_company_override() -> None:
    assert evaluate("llm_error_rate", 0.25, 0.0, {}) is True
    assert evaluate("llm_error_rate", 0.05, 0.0, {}) is False
    assert evaluate("llm_cost_usd", 3.0, 1.0, {"llm_cost_usd": 4.0}) is False  # company allows 4x
    assert evaluate("autonomy_unchanged_rate", 0.3, 0.8, {}) is True  # fewer drafts sent unchanged
    assert evaluate("llm_cost_usd", 3.0, None, {}) is False


def test_daily_cron_snapshots_every_company_without_failing(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company
) -> None:
    from dbos import DBOS

    from app.workflows import quality

    DBOS.start_workflow(quality.drift_cron, datetime(2026, 10, 7, 4, 30, tzinfo=UTC), None).get_result()
    with Session(migrated_engine) as s:
        assert s.scalar(
            select(MetricSnapshot.id).where(
                MetricSnapshot.company_id == committed_company.id, MetricSnapshot.day == DAY
            )
        )

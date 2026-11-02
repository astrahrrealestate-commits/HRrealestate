"""Unit tests for the concierge query_data intent and Custom Query Agent wiring."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

from sqlalchemy import create_engine

from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.settings import Settings
from app.pipeline import concierge, concierge_reads
from app.pipeline.concierge_base import NEED_DETAIL, Ctx
from app.tools.query_agent.agent import QueryAgentResponse

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)
COMPANY = UUID("01900000-0000-7000-8000-000000000001")


def _make_settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]


def test_query_data_missing_text_fails_with_need_detail() -> None:
    engine = create_engine("sqlite://")
    settings = _make_settings()
    ctx = Ctx(engine=engine, settings=settings, company_id=COMPANY, now=NOW, question="")
    step = PlanStep(intent=Intent.query_data, case_id=None, task_ref=None, text="", view=None)

    res = concierge_reads.query_data(ctx, step)
    assert not res.ok
    assert res.summary == NEED_DETAIL


def test_query_data_executes_query_agent() -> None:
    engine = create_engine("sqlite://")
    settings = _make_settings()
    ctx = Ctx(
        engine=engine,
        settings=settings,
        company_id=COMPANY,
        now=NOW,
        question="How many leases are expiring this year?",
    )
    step = PlanStep(
        intent=Intent.query_data,
        case_id=None,
        task_ref=None,
        text="How many leases are expiring this year?",
        view=None,
    )

    mock_resp = QueryAgentResponse(
        ok=True,
        answer="Found **3** leases expiring in 2026.",
        sql="SELECT unit_address, end_date FROM v_active_leases WHERE end_date <= '2026-12-31' LIMIT 50",
        rows=[{"unit_address": "Keizersgracht 101", "end_date": "2026-08-01"}],
        row_count=1,
        duration_ms=25.4,
    )

    with patch("app.tools.query_agent.agent.run_query_agent", return_value=mock_resp) as mock_run:
        res = concierge_reads.query_data(ctx, step)

        mock_run.assert_called_once_with(
            engine=engine,
            settings=settings,
            company_id=COMPANY,
            question="How many leases are expiring this year?",
        )
        assert res.ok
        assert res.intent == Intent.query_data
        assert res.summary == "Found **3** leases expiring in 2026."
        assert res.data["sql"] == mock_resp.sql
        assert res.data["row_count"] == 1


def test_query_data_in_run_plan() -> None:
    engine = create_engine("sqlite://")
    settings = _make_settings()
    plan = ConciergePlan(
        in_scope=True,
        steps=[
            PlanStep(
                intent=Intent.query_data,
                case_id=None,
                task_ref=None,
                text="Who owes rent?",
                view=None,
            )
        ],
        reply=None,
    )

    mock_resp = QueryAgentResponse(
        ok=True,
        answer="Found **1** tenant with arrears.",
        sql="SELECT tenant_name, arrears_amount FROM v_active_leases WHERE arrears_amount > 0 LIMIT 50",
        rows=[{"tenant_name": "Jan Jansen", "arrears_amount": 1250.00}],
        row_count=1,
        duration_ms=18.0,
    )

    with patch("app.tools.query_agent.agent.run_query_agent", return_value=mock_resp):
        results = concierge.run_plan(
            engine=engine,
            settings=settings,
            company_id=COMPANY,
            plan=plan,
            question="Who owes rent?",
            now=NOW,
        )

        assert len(results) == 1
        assert results[0].ok
        assert results[0].intent == Intent.query_data
        assert "Jan Jansen" in results[0].summary or results[0].data["rows"][0]["tenant_name"] == "Jan Jansen"

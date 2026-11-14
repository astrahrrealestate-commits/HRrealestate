"""run_agent enforces configured company limits and writes nothing for blocked attempts."""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.errors import AgentFailedError, BudgetExceededError
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.models import Company, ModelCall
from app.llm.agents.understanding import UNDERSTANDING
from app.llm.calls import CallContext, run_agent

pytestmark = pytest.mark.integration


def _count(engine: Engine, company: Company) -> int:
    with Session(engine) as s:
        return s.scalar(select(func.count()).select_from(ModelCall).where(ModelCall.company_id == company.id)) or 0


def test_no_limits_configured_never_blocks(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    ctx = CallContext(committed_company.id, "triage")
    for _ in range(3):
        run_agent(migrated_engine, test_settings, UNDERSTANDING, "Er lekt water", ctx)
    assert _count(migrated_engine, committed_company) == 3


def test_daily_call_cap_blocks_and_records_nothing(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    settings = test_settings.model_copy(update={"llm_daily_calls_cap": 1})
    ctx = CallContext(committed_company.id, "triage")
    run_agent(migrated_engine, settings, UNDERSTANDING, "Er lekt water", ctx)
    with pytest.raises(BudgetExceededError) as info:
        run_agent(migrated_engine, settings, UNDERSTANDING, "Er lekt water", ctx)
    assert info.value.scope == "daily_calls"
    assert isinstance(info.value, AgentFailedError)
    assert _count(migrated_engine, committed_company) == 1


def test_daily_spend_budget_blocks(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    spent = ModelCall(
        id=new_id(),
        company_id=committed_company.id,
        purpose="triage",
        prompt_name="understanding",
        prompt_version="v2",
        prompt_sha256="x",
        model="m",
        input={},
        cost_usd=Decimal("5"),
    )
    with Session(migrated_engine) as s, s.begin():
        s.add(spent)
    settings = test_settings.model_copy(update={"llm_daily_budget_usd": Decimal("1")})
    with pytest.raises(BudgetExceededError, match="daily_budget"):
        run_agent(migrated_engine, settings, UNDERSTANDING, "x", CallContext(committed_company.id, "triage"))


def test_owner_qa_cap_does_not_block_other_purposes(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    settings = test_settings.model_copy(update={"owner_qa_daily_cap": 0})
    run_agent(migrated_engine, settings, UNDERSTANDING, "Er lekt water", CallContext(committed_company.id, "triage"))
    with pytest.raises(BudgetExceededError, match="owner_qa_daily_calls"):
        run_agent(migrated_engine, settings, UNDERSTANDING, "x", CallContext(committed_company.id, "owner_qa"))

"""The fixed-answer intents of concierge/v8 (`calendar`, `rent_status`): each answers its own step only, so it
composes with the other steps of the same plan (the rent answer used to pre-empt the planner by keyword)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.api.agent import rent_guard
from app.contracts import ConciergePlan, Intent, PlanStep
from app.core import rent_data
from app.core.settings import Settings
from app.pipeline import case_repo, concierge, concierge_reads
from app.pipeline.concierge_base import Ctx, StepResult
from app.pipeline.concierge_reads import CALENDAR_POINTER, NO_RENT_DATA_ANSWER

NOW = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
COMPANY = UUID("01900000-0000-7000-8000-000000000001")
CASE = UUID("01900000-0000-7000-8000-0000000000ca")


def _step(intent: Intent, text: str | None = None, case_id: UUID | None = None) -> PlanStep:
    return PlanStep(intent=intent, case_id=case_id, task_ref=None, text=text, view=None)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Never queried: these handlers read nothing; sessions only need a bind."""
    eng = create_engine("sqlite://")
    yield eng
    eng.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]


@pytest.fixture
def ctx(engine: Engine, settings: Settings) -> Ctx:
    return Ctx(engine=engine, settings=settings, company_id=COMPANY, now=NOW, question="who owes rent?")


@pytest.fixture
def no_query_agent(monkeypatch: pytest.MonkeyPatch) -> list[PlanStep]:
    calls: list[PlanStep] = []

    def spy(_ctx: Ctx, step: PlanStep) -> StepResult:
        calls.append(step)
        return StepResult(step.intent, True, "3 tenants are behind.", None, None)

    monkeypatch.setattr(concierge_reads, "query_data", spy)
    return calls


def test_calendar_step_returns_a_calendar_pointer(ctx: Ctx) -> None:
    result = concierge_reads.calendar(ctx, _step(Intent.calendar, "book the plumber at evil.example on Thursday"))
    assert (result.intent, result.ok, result.summary, result.data) == (Intent.calendar, True, CALENDAR_POINTER, None)
    assert "Calendar" in result.summary
    assert "evil" not in result.summary  # the model's text is never echoed


def test_rent_status_is_honest_while_no_rent_data(ctx: Ctx, no_query_agent: list[PlanStep]) -> None:
    assert rent_data.RENT_DATA_AVAILABLE is False
    result = concierge_reads.rent_status(ctx, _step(Intent.rent_status))
    expected = (Intent.rent_status, True, NO_RENT_DATA_ANSWER, None)
    assert (result.intent, result.ok, result.summary, result.data) == expected
    assert no_query_agent == []  # no figure is computed from data that does not exist


def test_rent_status_asks_the_query_agent_once_rent_data_exists(
    ctx: Ctx, no_query_agent: list[PlanStep], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rent_data, "RENT_DATA_AVAILABLE", True)
    result = concierge_reads.rent_status(ctx, _step(Intent.rent_status))
    assert result.summary == "3 tenants are behind."
    assert no_query_agent == [_step(Intent.rent_status)]


def test_rent_answer_text_is_defined_once_and_re_exported_by_the_rent_guard() -> None:
    assert rent_guard.NO_RENT_DATA_ANSWER is NO_RENT_DATA_ANSWER
    assert not hasattr(concierge_reads, "REWRITE_UNSUPPORTED_ANSWER")  # a redraft is `draft_reply`, not refused


def test_rent_status_beside_a_draft_step_keeps_both_results(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch, no_query_agent: list[PlanStep]
) -> None:
    monkeypatch.setattr(case_repo, "get_case", lambda _s, _c, _id: object())
    drafted = StepResult(Intent.draft_reply, True, "Reply drafted for approval.", {"case_id": str(CASE)}, None)
    monkeypatch.setitem(concierge._HANDLERS, Intent.draft_reply, lambda _ctx, _step: drafted)
    steps = [_step(Intent.draft_reply, case_id=CASE), _step(Intent.rent_status)]
    plan = ConciergePlan(in_scope=True, steps=steps, reply=None)
    results = concierge.run_plan(
        engine, settings, COMPANY, plan, question="draft a reminder about the unpaid rent", now=NOW, brief_cases=[CASE]
    )
    assert results == [drafted, StepResult(Intent.rent_status, True, NO_RENT_DATA_ANSWER, None, None)]
    with Session(engine) as session:
        assert concierge.validate_plan(session, COMPANY, plan, {CASE}) == steps

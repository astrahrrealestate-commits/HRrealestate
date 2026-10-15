"""Concierge executor without Postgres: dispatch table, scope gate, argument checks, fail-soft, transient errors."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.errors import NotFoundError
from app.core.settings import Settings
from app.llm.agents.owner_qa import REFUSAL_ANSWER
from app.pipeline import case_repo, concierge, concierge_writes, work_repo
from app.pipeline.concierge_base import NEED_DETAIL, NOT_FOUND, STEP_FAILED, Ctx, StepResult, task_ref

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
COMPANY = UUID("01900000-0000-7000-8000-000000000001")
KNOWN_CASE = UUID("01900000-0000-7000-8000-0000000000ca")
FOREIGN_CASE = UUID("01900000-0000-7000-8000-0000000000fe")
KNOWN_TASK = "a1b2c3"


def step(intent: Intent, **kw: Any) -> PlanStep:
    return PlanStep(
        intent=intent,
        case_id=kw.get("case_id"),
        task_ref=kw.get("task_ref"),
        text=kw.get("text"),
        view=kw.get("view"),
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    """Never queried: repository lookups are faked below; sessions only need a bind."""
    eng = create_engine("sqlite://")
    yield eng
    eng.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", env="test", _env_file=None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def fake_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_case(_s: Session, company_id: UUID, case_id: UUID) -> object:
        if company_id != COMPANY or case_id != KNOWN_CASE:
            raise NotFoundError("case")
        return object()

    def resolve_task(_s: Session, company_id: UUID, ref: str) -> UUID:
        if company_id != COMPANY or ref != KNOWN_TASK:
            raise NotFoundError("task")
        return KNOWN_CASE

    monkeypatch.setattr(case_repo, "get_case", get_case)
    monkeypatch.setattr(work_repo, "resolve_task", resolve_task)


class Spy:
    def __init__(self, result: StepResult | None = None, raises: BaseException | None = None) -> None:
        self.calls: list[PlanStep] = []
        self.result, self.raises = result, raises

    def __call__(self, ctx: Ctx, s: PlanStep) -> StepResult:
        self.calls.append(s)
        if self.raises is not None:
            raise self.raises
        return self.result or StepResult(s.intent, True, "ok", None, None)


def _spy_all(monkeypatch: pytest.MonkeyPatch) -> dict[Intent, Spy]:
    spies = {i: Spy() for i in Intent}
    monkeypatch.setattr(concierge, "_HANDLERS", dict(spies))
    return spies


def test_every_intent_has_a_handler() -> None:
    assert set(concierge._HANDLERS) == set(Intent)


def test_contract_rejects_more_than_four_steps() -> None:
    with pytest.raises(ValidationError):
        ConciergePlan(in_scope=True, steps=[step(Intent.list_tasks)] * 5)


def test_out_of_scope_runs_nothing_even_with_steps(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings
) -> None:
    spies = _spy_all(monkeypatch)
    plan = ConciergePlan.model_construct(in_scope=False, steps=[step(Intent.pause), step(Intent.draft_reply)])
    results = concierge.run_plan(engine, settings, COMPANY, plan, question="q", now=NOW)
    assert [(r.ok, r.summary) for r in results] == [(False, REFUSAL_ANSWER)]
    assert all(not s.calls for s in spies.values())
    with Session(engine) as session:
        assert concierge.validate_plan(session, COMPANY, plan) == []


def test_at_most_four_steps_run(monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings) -> None:
    spies = _spy_all(monkeypatch)
    plan = ConciergePlan.model_construct(in_scope=True, steps=[step(Intent.list_tasks)] * 6)
    assert len(concierge.run_plan(engine, settings, COMPANY, plan, question="q", now=NOW)) == 4
    assert len(spies[Intent.list_tasks].calls) == 4


@pytest.mark.parametrize(
    "bad",
    [
        step(Intent.case_status),
        step(Intent.draft_reply),
        step(Intent.chase_now),
        step(Intent.task_done),
        step(Intent.task_snooze, task_ref=KNOWN_TASK),
        step(Intent.task_snooze, text="2d"),
        step(Intent.create_task, text="   "),
        step(Intent.clarify),
        step(Intent.search_inbox),
        step(Intent.open_view),
    ],
)
def test_missing_argument_needs_detail(bad: PlanStep, engine: Engine) -> None:
    assert concierge.needs_detail(bad)
    with Session(engine) as session:
        assert concierge.check_step(session, COMPANY, bad) == NEED_DETAIL


@pytest.mark.parametrize(
    "bad",
    [
        step(Intent.case_status, case_id=FOREIGN_CASE),
        step(Intent.draft_reply, case_id=FOREIGN_CASE),
        step(Intent.open_view, view="cases", case_id=FOREIGN_CASE),
        step(Intent.task_done, task_ref="ffffff"),
        step(Intent.task_done, task_ref="%%%%%%"),
        step(Intent.task_snooze, task_ref="______", text="2d"),
    ],
)
def test_unknown_or_foreign_ref_is_not_found(bad: PlanStep, engine: Engine) -> None:
    with Session(engine) as session:
        assert concierge.check_step(session, COMPANY, bad) == NOT_FOUND


def test_validate_keeps_good_steps_in_order(engine: Engine) -> None:
    good = [step(Intent.case_status, case_id=KNOWN_CASE), step(Intent.task_done, task_ref=f"#{KNOWN_TASK.upper()}")]
    plan = ConciergePlan(in_scope=True, steps=[good[0], step(Intent.case_status, case_id=FOREIGN_CASE), good[1]])
    with Session(engine) as session:
        assert concierge.validate_plan(session, COMPANY, plan) == good


def test_bad_step_fails_alone_and_plan_continues(
    monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings
) -> None:
    spies = _spy_all(monkeypatch)
    plan = ConciergePlan(in_scope=True, steps=[step(Intent.draft_reply, case_id=FOREIGN_CASE), step(Intent.list_tasks)])
    results = concierge.run_plan(engine, settings, COMPANY, plan, question="q", now=NOW)
    assert [(r.ok, r.summary) for r in results] == [(False, NOT_FOUND), (True, "ok")]
    assert not spies[Intent.draft_reply].calls


def test_handler_error_fails_its_step_only(monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings) -> None:
    spies = _spy_all(monkeypatch)
    spies[Intent.pause].raises = IntegrityError("stmt", {}, Exception("secret body text"))
    plan = ConciergePlan(in_scope=True, steps=[step(Intent.pause), step(Intent.list_waiting)])
    results = concierge.run_plan(engine, settings, COMPANY, plan, question="q", now=NOW)
    assert [(r.ok, r.summary) for r in results] == [(False, STEP_FAILED), (True, "ok")]


@pytest.mark.parametrize("exc", [OperationalError("stmt", {}, Exception("down")), ConnectionError("reset")])
def test_transient_error_propagates(
    exc: Exception, monkeypatch: pytest.MonkeyPatch, engine: Engine, settings: Settings
) -> None:
    spies = _spy_all(monkeypatch)
    spies[Intent.list_tasks].raises = exc
    plan = ConciergePlan(in_scope=True, steps=[step(Intent.list_tasks), step(Intent.list_waiting)])
    with pytest.raises(type(exc)):
        concierge.run_plan(engine, settings, COMPANY, plan, question="q", now=NOW)
    assert not spies[Intent.list_waiting].calls


@pytest.mark.parametrize("raw", ["99y", "0d", "9999d", "soon", "+31612345678"])
def test_snooze_bad_duration_fails_before_any_lookup(raw: str, engine: Engine, settings: Settings) -> None:
    ctx = Ctx(engine=engine, settings=settings, company_id=COMPANY, now=NOW, question="q")
    result = concierge_writes.task_snooze(ctx, step(Intent.task_snooze, task_ref=KNOWN_TASK, text=raw))
    assert not result.ok
    assert "use 30m" in result.summary or "between 1 minute and 8 weeks" in result.summary
    assert "3161234" not in result.summary


def test_task_ref_normalisation() -> None:
    assert task_ref("#A1B2C3") == "a1b2c3"
    assert task_ref("a1b2c3d4") == "a1b2c3d4"
    assert task_ref("a1b2") is None
    assert task_ref("a1b2c%") is None
    assert task_ref(None) is None


def test_create_task_without_usable_title_needs_detail(engine: Engine, settings: Settings) -> None:
    ctx = Ctx(engine=engine, settings=settings, company_id=COMPANY, now=NOW, question="q")
    result = concierge_writes.create_task(ctx, step(Intent.create_task, text="​​"))
    assert (result.ok, result.summary) == (False, NEED_DETAIL)

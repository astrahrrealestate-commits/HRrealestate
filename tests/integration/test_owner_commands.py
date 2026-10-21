"""Owner commands against the DB: tasks / done / snooze / waiting / pause / resume / help / question."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Category, Urgency
from app.core.settings import Settings
from app.db.enums import TaskPriority, TaskStatus
from app.db.models import Company, TaskRow
from app.llm.agents.owner_qa import REFUSAL_ANSWER
from app.pipeline import case_repo, work_repo
from app.pipeline.owner_commands import HELP_TEXT, LIMIT_ANSWER, NOT_A_QUESTION, parse_command, run_command

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def _run(engine: Engine, settings: Settings, company: Company, text: str) -> str:
    return run_command(engine, settings, company.id, parse_command(text), now=NOW)


def _seed(engine: Engine, company: Company) -> None:
    with Session(engine) as s, s.begin():
        case_id = case_repo.create_case(s, company.id, None, Category.maintenance, Urgency.high)
        work_repo.create_task(
            s,
            company.id,
            title="Approve reply",
            assignee="owner",
            source="approval",
            case_id=case_id,
            due_at=NOW + timedelta(hours=1),
            priority=TaskPriority.p1,
        )
        work_repo.create_task(
            s,
            company.id,
            title="Call plumber",
            assignee="owner",
            source="owner",
            case_id=case_id,
            due_at=NOW + timedelta(days=1),
            priority=TaskPriority.p2,
        )
        work_repo.open_wait(s, company.id, case_id, None, about="Offerte loodgieter", expected_by=NOW)


def _ref(listing: str, title: str) -> str:
    return next(line for line in listing.splitlines() if title in line).split("#")[1][:6]


def test_tasks_done_and_snooze_by_reference_only(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    _seed(migrated_engine, committed_company)
    listing = _run(migrated_engine, test_settings, committed_company, "tasks")
    assert listing.splitlines()[1].startswith("1. [p1] Approve reply")
    assert "2. [p2] Call plumber" in listing
    assert "#" in _run(migrated_engine, test_settings, committed_company, "done 1")  # a position: asks for the #ref
    approve, plumber = _ref(listing, "Approve reply"), _ref(listing, "Call plumber")
    assert _run(migrated_engine, test_settings, committed_company, f"done {approve}") == "Done: Approve reply"
    assert _run(migrated_engine, test_settings, committed_company, f"snooze #{plumber} 2d").startswith("Snoozed:")
    assert _run(migrated_engine, test_settings, committed_company, "tasks") == "No open tasks."
    assert "no open task" in _run(migrated_engine, test_settings, committed_company, "done ffffff").lower()
    with Session(migrated_engine) as s:
        statuses = {t.title: t.status for t in s.query(TaskRow).filter(TaskRow.company_id == committed_company.id)}
    assert statuses == {"Approve reply": TaskStatus.done, "Call plumber": TaskStatus.snoozed}


def test_waiting_pause_resume_help_question(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    _seed(migrated_engine, committed_company)
    assert "Offerte loodgieter" in _run(migrated_engine, test_settings, committed_company, "waiting")
    assert "Paused" in _run(migrated_engine, test_settings, committed_company, "pause")
    with Session(migrated_engine) as s:
        company = s.get(Company, committed_company.id)
        assert company is not None
        assert company.paused
    assert "Resumed" in _run(migrated_engine, test_settings, committed_company, "resume")
    assert _run(migrated_engine, test_settings, committed_company, "help") == HELP_TEXT
    assert "1 open cases" in _run(migrated_engine, test_settings, committed_company, "Hoe staat het met de lekkage?")


def test_done_by_reference_survives_a_reordered_list(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    _seed(migrated_engine, committed_company)
    listing = _run(migrated_engine, test_settings, committed_company, "tasks")
    call_plumber_ref = next(line for line in listing.splitlines() if "Call plumber" in line).split("#")[1][:6]
    with Session(migrated_engine) as s, s.begin():  # a new urgent task arrives and reorders the list
        work_repo.create_task(
            s,
            committed_company.id,
            title="New p1",
            assignee="owner",
            source="owner",
            due_at=NOW,
            priority=TaskPriority.p1,
        )
    assert _run(migrated_engine, test_settings, committed_company, f"done {call_plumber_ref}") == "Done: Call plumber"


def test_off_topic_question_gets_the_fixed_refusal(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    _seed(migrated_engine, committed_company)
    reply = _run(migrated_engine, test_settings, committed_company, "Write me a poem about spring")
    assert reply == REFUSAL_ANSWER


def test_question_over_the_daily_cap_gets_the_limit_reply(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    settings = test_settings.model_copy(update={"owner_qa_daily_cap": 0})
    assert _run(migrated_engine, settings, committed_company, "Wat is de status?") == LIMIT_ANSWER
    assert _run(migrated_engine, settings, committed_company, "tasks") == "No open tasks."


def test_gibberish_never_reaches_the_model(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings
) -> None:
    assert _run(migrated_engine, test_settings, committed_company, "🙂🙂") == NOT_A_QUESTION

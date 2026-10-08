"""Briefing (#7): facts from the DB, agent text (fallback template), daily/weekly timers per company timezone."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, TaskPriority
from app.db.models import ActionRow, Company, Timer
from app.pipeline import approvals, briefing, case_repo, work_repo

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 5, 30, tzinfo=UTC)  # 07:30 Amsterdam (CEST)


def _seed(engine: Engine, company: Company) -> None:
    with Session(engine) as s, s.begin():
        urgent = case_repo.create_case(s, company.id, None, Category.maintenance, Urgency.emergency)
        a = ActionRow(
            company_id=company.id,
            case_id=urgent,
            type=ActionType.escalate,
            payload={"kind": "escalate", "reason": "Flood"},
            rationale="r",
            context_ref=[],
            status=ActionStatus.pending_approval,
        )
        s.add(a)
        s.flush()
        approvals.open_approval(s, company.id, a.id, 1, urgency=Urgency.emergency, now=NOW - timedelta(hours=3))
        work_repo.create_task(
            s,
            company.id,
            title="Call plumber",
            assignee="owner",
            source="owner",
            due_at=NOW - timedelta(hours=1),
            priority=TaskPriority.p1,
        )
        work_repo.open_wait(
            s, company.id, urgent, None, about="Offerte loodgieter", expected_by=NOW - timedelta(days=1)
        )


def test_daily_facts_and_text(migrated_engine: Engine, committed_company: Company, test_settings: Settings) -> None:
    _seed(migrated_engine, committed_company)
    facts = briefing.collect(migrated_engine, committed_company.id, "daily", NOW)
    assert len(facts.urgent) == 1
    assert len(facts.approvals) == 1
    assert [t for t in facts.overdue_tasks if "Call plumber" in t]
    assert [w for w in facts.overdue_waits if "Offerte loodgieter" in w]
    text = briefing.compose(migrated_engine, test_settings, committed_company.id, "daily", NOW)
    assert text.startswith("Good morning")
    assert "Call plumber" in text
    assert len(text) <= 4096


def test_weekly_adds_counts(migrated_engine: Engine, committed_company: Company, test_settings: Settings) -> None:
    _seed(migrated_engine, committed_company)
    facts = briefing.collect(migrated_engine, committed_company.id, "weekly", NOW)
    assert facts.stats["cases opened"] == 1
    assert "Week" in briefing.compose(migrated_engine, test_settings, committed_company.id, "weekly", NOW)


def test_fallback_when_agent_fails(
    migrated_engine: Engine, committed_company: Company, test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    bad = FunctionModel(lambda m, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"x": 1})]))
    monkeypatch.setattr("app.llm.calls.build_model", lambda _s, _n: bad)
    _seed(migrated_engine, committed_company)
    text = briefing.compose(migrated_engine, test_settings, committed_company.id, "daily", NOW)
    assert "Call plumber" in text  # deterministic template still lists everything


def test_next_run_times_follow_company_timezone(migrated_engine: Engine, committed_company: Company) -> None:
    with Session(migrated_engine) as s, s.begin():
        created = briefing.ensure_timers(s, NOW + timedelta(minutes=1))
    assert created >= 2
    with Session(migrated_engine) as s:
        due = dict(s.execute(select(Timer.kind, Timer.due_at).where(Timer.company_id == committed_company.id)).all())
    assert due[briefing.DAILY] == datetime(2026, 10, 8, 5, 30, tzinfo=UTC)  # tomorrow 07:30 Amsterdam
    assert due[briefing.WEEKLY] == datetime(2026, 10, 9, 14, 0, tzinfo=UTC)  # Friday 16:00 Amsterdam
    with Session(migrated_engine) as s, s.begin():
        assert briefing.ensure_timers(s, NOW + timedelta(minutes=2)) == 0  # idempotent


def test_failed_messages_and_unexecuted_approvals_reach_the_briefing(
    migrated_engine: Engine, committed_company: Company
) -> None:
    from app.contracts import Channel, Direction
    from app.core.ids import new_id
    from app.db.enums import PipelineStatus
    from app.db.models import MessageRow, RawEvent

    with Session(migrated_engine) as s, s.begin():
        raw = RawEvent(
            company_id=committed_company.id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={}
        )
        s.add(raw)
        s.flush()
        s.add(
            MessageRow(
                company_id=committed_company.id,
                raw_event_id=raw.id,
                channel=Channel.gmail,
                provider_msg_id=raw.provider_msg_id,
                sender_identity="x@example.test",
                direction=Direction.inbound,
                sent_at=NOW,
                text="?",
                pipeline_status=PipelineStatus.failed,
                pipeline_attempts=3,
            )
        )
        case_id = case_repo.create_case(s, committed_company.id, None, Category.other, Urgency.normal)
        s.add(
            ActionRow(
                company_id=committed_company.id,
                case_id=case_id,
                type=ActionType.notify_owner,
                payload={"kind": "notify_owner", "text": "x"},
                rationale="r",
                context_ref=[],
                status=ActionStatus.failed,
            )
        )
    facts = briefing.collect(migrated_engine, committed_company.id, "daily", NOW + timedelta(hours=1))
    assert any("could not be processed" in e for e in facts.exceptions)
    assert any("not delivered" in e for e in facts.exceptions)

"""Cases, tasks, waits, briefing, activity and company reads against real Postgres: company scoping and shapes."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import ActionType, CaseState, Category, Channel, OutboundMode, Urgency
from app.core.settings import Settings
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    CaseEventKind,
    OutcomeLabel,
    OutcomeSource,
    SendStatus,
)
from app.db.models import ActionRow, Approval, Case, CaseEvent, Company, Outcome, OwnerAccount, Send, TaskRow, WaitRow
from app.main import create_app
from app.pipeline.work_repo import short_ref

pytestmark = pytest.mark.integration
T0 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class World:
    client: TestClient
    case_a: UUID
    case_b: UUID
    task_a: UUID
    action_a: UUID


def _company_rows(s: Session, company: Company, tag: str) -> tuple[UUID, UUID, UUID]:
    case = Case(company_id=company.id, category=Category.other, urgency=Urgency.high, summary=f"case {tag}")
    s.add(case)
    s.flush()
    action = ActionRow(
        company_id=company.id, case_id=case.id, type=ActionType.reply_to_sender, payload={"drafts": [tag]},
        rationale="r", context_ref=[], status=ActionStatus.pending_approval,
    )  # fmt: skip
    task = TaskRow(company_id=company.id, case_id=case.id, title=f"task {tag}", assignee="owner", source="owner")
    s.add_all([action, task])
    s.flush()
    s.add_all(
        [
            Approval(company_id=company.id, action_id=action.id, draft_version=1, status=ApprovalStatus.pending),
            WaitRow(company_id=company.id, case_id=case.id, about=f"wait {tag}", expected_by=T0),
            CaseEvent(company_id=company.id, case_id=case.id, kind=CaseEventKind.note, note=f"ev {tag}", actor="owner"),
            Send(company_id=company.id, action_id=action.id, idempotency_key=f"k-{tag}-{uuid4()}",
                 channel=Channel.whatsapp, target="+31", status=SendStatus.sent),
            Outcome(company_id=company.id, action_id=action.id, draft_version=1, final_text="t",
                    label=OutcomeLabel.unchanged, source=OutcomeSource.echo),
        ]
    )  # fmt: skip
    s.flush()
    return case.id, task.id, action.id


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.flush()
        owner = OwnerAccount(company_id=a.id, display_name="H", whatsapp_e164="+31699999997", email="h@a.test")
        s.add(owner)
        case_a, task_a, action_a = _company_rows(s, a, "a")
        case_b, _, _ = _company_rows(s, b, "b")
        s.commit()
        settings = Settings(  # type: ignore[call-arg]
            database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32), _env_file=None
        )
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock())
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, case_a, case_b, task_a, action_a)
        ids = [a.id, b.id]
        for model in (Outcome, Send, Approval, WaitRow, TaskRow, CaseEvent, ActionRow, Case):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(OwnerAccount).filter(OwnerAccount.id == owner.id).delete()
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def test_cases_list_only_own(world: World) -> None:
    body = world.client.get("/api/v1/cases").json()
    assert [c["id"] for c in body] == [str(world.case_a)]
    assert world.client.get("/api/v1/cases", params={"state": CaseState.resolved.value}).json() == []


def test_case_detail_has_timeline_actions_and_live_approval(world: World) -> None:
    body = world.client.get(f"/api/v1/cases/{world.case_a}").json()
    assert [e["note"] for e in body["timeline"]] == ["ev a"]
    assert body["actions"][0]["approval"]["status"] == "pending"
    assert body["actions"][0]["approval"]["draft_version"] == 1
    assert body["actions"][0]["payload"] == {"drafts": ["a"]}


def test_foreign_case_404_matches_random_uuid(world: World) -> None:
    foreign = world.client.get(f"/api/v1/cases/{world.case_b}")
    random = world.client.get(f"/api/v1/cases/{uuid4()}")
    assert foreign.status_code == random.status_code == 404
    assert foreign.json() == random.json()


def test_tasks_own_with_short_ref(world: World) -> None:
    body = world.client.get("/api/v1/tasks").json()
    assert [t["title"] for t in body] == ["task a"]
    assert body[0]["ref"] == short_ref(world.task_a)


def test_waits_own_only(world: World) -> None:
    assert [w["about"] for w in world.client.get("/api/v1/waits").json()] == ["wait a"]


def test_activity_own_merged_and_bounded(world: World) -> None:
    body = world.client.get("/api/v1/activity").json()
    assert sorted(i["kind"] for i in body) == ["case_event", "outcome", "send"]
    assert {i["action_id"] for i in body if i["kind"] != "case_event"} == {str(world.action_a)}
    assert len(world.client.get("/api/v1/activity", params={"limit": 2}).json()) == 2
    times = [i["at"] for i in body]
    assert times == sorted(times, reverse=True)


def test_briefing_counts_only_own(world: World) -> None:
    body = world.client.get("/api/v1/briefing").json()
    assert len(body["urgent"]) == 1
    assert len(body["overdue_waits"]) == 1
    assert len(body["approvals"]) == 1


def test_company_defaults(world: World) -> None:
    body = world.client.get("/api/v1/company").json()
    expected = {"name": "A", "paused": False, "outbound_mode": OutboundMode.draft.value}
    assert body == {**expected, "timezone": "Europe/Amsterdam"}


def test_timeline_capped_at_newest_100(world: World, migrated_engine: Engine) -> None:
    with Session(migrated_engine) as s:
        case = s.get(Case, world.case_a)
        assert case is not None
        for i in range(120):
            s.add(CaseEvent(company_id=case.company_id, case_id=case.id, kind=CaseEventKind.note, note=f"n{i}",
                            actor="system", created_at=T0 + timedelta(minutes=i + 1)))  # fmt: skip
        s.commit()
    timeline = world.client.get(f"/api/v1/cases/{world.case_a}").json()["timeline"]
    assert len(timeline) == 100
    assert timeline[-1]["note"] == "n119"

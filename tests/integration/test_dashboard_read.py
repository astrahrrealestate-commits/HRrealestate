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
from app.contracts import ActionType, CaseState, Category, Channel, Direction, OutboundMode, Urgency
from app.core.settings import Settings
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    CaseEventKind,
    LinkMethod,
    OutcomeLabel,
    OutcomeSource,
    SendStatus,
    TaskStatus,
    WaitStatus,
)
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    Outcome,
    OwnerAccount,
    Send,
    TaskRow,
    WaitRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
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
    cid: UUID
    engine: Engine


def _company_rows(s: Session, company: Company, tag: str) -> tuple[UUID, UUID, UUID]:
    case = Case(company_id=company.id, category=Category.other, urgency=Urgency.high, summary=f"case {tag}")
    s.add(case)
    s.flush()
    action = ActionRow(
        company_id=company.id, case_id=case.id, type=ActionType.reply_draft, payload={"drafts": [tag]},
        rationale="r", context_ref=[], status=ActionStatus.pending_approval,
    )  # fmt: skip
    task = TaskRow(company_id=company.id, case_id=case.id, title=f"task {tag}", assignee="owner", source="owner")
    s.add_all([action, task])
    s.flush()
    s.add_all(
        [
            Approval(company_id=company.id, action_id=action.id, draft_version=1, status=ApprovalStatus.pending),
            WaitRow(company_id=company.id, case_id=case.id, about=f"wait {tag}", expected_by=T0),
            CaseEvent(company_id=company.id, case_id=case.id, kind=CaseEventKind.note, note=f"ev {tag}", actor="owner",
                      created_at=T0),
            Send(company_id=company.id, action_id=action.id, idempotency_key=f"k-{tag}-{uuid4()}",
                 channel=Channel.whatsapp, target="+31", status=SendStatus.sent, created_at=T0 + timedelta(minutes=1)),
            Outcome(company_id=company.id, action_id=action.id, draft_version=1, final_text="t",
                    label=OutcomeLabel.unchanged, source=OutcomeSource.echo, created_at=T0 + timedelta(minutes=2)),
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
        settings = Settings(
            database_url=pg_url,  # type: ignore[arg-type]
            env="test",
            dashboard_session_secret=SecretStr("x" * 32),
            _env_file=None,
        )
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock())
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, case_a, case_b, task_a, action_a, a.id, migrated_engine)
        ids = [a.id, b.id]
        for model in (
            CaseLink,
            MessageRow,
            RawEvent,
            Outcome,
            Send,
            Approval,
            WaitRow,
            TaskRow,
            CaseEvent,
            ActionRow,
            Case,
        ):
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


def test_timeline_capped_at_newest_100(world: World) -> None:
    with Session(world.engine) as s:
        for i in range(120):
            s.add(CaseEvent(company_id=world.cid, case_id=world.case_a, kind=CaseEventKind.note, note=f"n{i}",
                            actor="system", created_at=T0 + timedelta(minutes=i + 10)))  # fmt: skip
        s.commit()
    timeline = world.client.get(f"/api/v1/cases/{world.case_a}").json()["timeline"]
    notes = [e["note"] for e in timeline]
    assert len(notes) == 100
    assert notes[-1] == "n119"
    assert "n0" not in notes
    assert "ev a" not in notes


def test_activity_label_never_carries_note_text(world: World) -> None:
    with Session(world.engine) as s:
        s.add(CaseEvent(company_id=world.cid, case_id=world.case_a, kind=CaseEventKind.state_change, actor="owner",
                        from_state=CaseState.open, to_state=CaseState.resolved, note="secret tenant words",
                        created_at=T0 + timedelta(hours=1)))  # fmt: skip
        s.commit()
    body = world.client.get("/api/v1/activity").json()
    assert body[0]["label"] == "state_change: open\u2192resolved"
    assert all("ev a" not in i["label"] and "secret" not in i["label"] for i in body)
    assert {i["label"] for i in body if i["kind"] == "case_event"} == {"note", "state_change: open\u2192resolved"}


def test_activity_send_and_outcome_carry_case_id(world: World) -> None:
    body = world.client.get("/api/v1/activity").json()
    assert {i["case_id"] for i in body} == {str(world.case_a)}


def test_activity_limit_bounds_each_source_and_result(world: World) -> None:
    with Session(world.engine) as s:
        for i in range(5):
            s.add(CaseEvent(company_id=world.cid, case_id=world.case_a, kind=CaseEventKind.note, actor="system",
                            created_at=T0 + timedelta(hours=1, minutes=i)))  # fmt: skip
        s.commit()
    body = world.client.get("/api/v1/activity", params={"limit": 3}).json()
    assert len(body) == 3
    assert {i["kind"] for i in body} == {"case_event"}  # the 3 newest are all events
    times = [i["at"] for i in body]
    assert times == sorted(times, reverse=True)


def test_case_detail_lists_linked_message_ids(world: World) -> None:
    with Session(world.engine) as s:
        raw = RawEvent(company_id=world.cid, provider=Channel.gmail, provider_msg_id="lk1", payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(company_id=world.cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id="lk1",
                         thread_ref="<t>", sender_identity="x@y.test", direction=Direction.inbound, sent_at=T0,
                         text="hi")  # fmt: skip
        s.add(msg)
        s.flush()
        s.add(CaseLink(company_id=world.cid, case_id=world.case_a, message_id=msg.id, method=LinkMethod.thread))
        s.commit()
        msg_id = msg.id
    assert world.client.get(f"/api/v1/cases/{world.case_a}").json()["message_ids"] == [str(msg_id)]


def test_tasks_exclude_future_snoozed_and_done(world: World) -> None:
    now = datetime.now(UTC)
    with Session(world.engine) as s:
        for title, status, until in (
            ("snoozed future", TaskStatus.snoozed, now + timedelta(days=1)),
            ("snoozed over", TaskStatus.snoozed, now - timedelta(days=1)),
            ("finished", TaskStatus.done, None),
        ):
            s.add(TaskRow(company_id=world.cid, title=title, assignee="owner", source="owner", status=status,
                          snoozed_until=until))  # fmt: skip
        s.commit()
    titles = {t["title"] for t in world.client.get("/api/v1/tasks").json()}
    assert titles == {"task a", "snoozed over"}


def test_waits_exclude_non_waiting(world: World) -> None:
    with Session(world.engine) as s:
        other = Case(company_id=world.cid, category=Category.other, urgency=Urgency.normal)
        s.add(other)
        s.flush()
        s.add(WaitRow(company_id=world.cid, case_id=other.id, about="got it", expected_by=T0,
                      status=WaitStatus.received))  # fmt: skip
        s.commit()
    assert [w["about"] for w in world.client.get("/api/v1/waits").json()] == ["wait a"]


def test_cases_state_filter_matches(world: World) -> None:
    with Session(world.engine) as s:
        s.add(Case(company_id=world.cid, category=Category.other, urgency=Urgency.normal, state=CaseState.resolved))
        s.commit()
    open_ids = [c["id"] for c in world.client.get("/api/v1/cases", params={"state": "open"}).json()]
    resolved = world.client.get("/api/v1/cases", params={"state": "resolved"}).json()
    assert open_ids == [str(world.case_a)]
    assert len(resolved) == 1
    assert resolved[0]["state"] == "resolved"

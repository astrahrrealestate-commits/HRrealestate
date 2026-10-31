"""SPA approve buttons (/api/inbox, /api/maintenance) decide through the canonical approval path and only enqueue
`exec:{action_id}:{draft_version}`: the API never sends (invariant 5), the sender does, behind `outbound_mode`."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, LinkMethod
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    Company,
    OwnerFeed,
    Send,
    TaskRow,
    UnderstandingRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app

pytestmark = pytest.mark.integration
T0 = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@dataclass
class World:
    client: TestClient
    wf: FakeClient
    engine: Engine
    company: UUID
    case: UUID
    action: UUID
    approval: UUID


def _seed(s: Session, company: Company, *, suspicious: bool) -> tuple[UUID, UUID, UUID]:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.high, summary="Lekkage")
    s.add(case)
    s.flush()
    action = ActionRow(
        company_id=company.id, case_id=case.id, type=ActionType.reply_draft,
        payload={"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["A", "B"]},
        rationale="r", context_ref=[], status=ActionStatus.pending_approval,
    )  # fmt: skip
    raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=f"m-{uuid4()}", payload={})
    s.add_all([action, raw])
    s.flush()
    msg = MessageRow(company_id=company.id, raw_event_id=raw.id, channel=Channel.gmail,
                     provider_msg_id=raw.provider_msg_id, thread_ref=f"t-{uuid4()}", sender_identity="x@y.test",
                     direction=Direction.inbound, sent_at=T0, text="Lekkage")  # fmt: skip
    s.add(msg)
    s.flush()
    approval = Approval(company_id=company.id, action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
    s.add_all([approval, CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread)])
    s.add(UnderstandingRow(company_id=company.id, message_id=msg.id, category=Category.maintenance,
                           urgency=Urgency.high, body={"suspicious": {"flag": suspicious}},
                           prompt_version="understanding/v2"))  # fmt: skip
    s.flush()
    action.context_ref = [msg.id]
    s.flush()
    return case.id, action.id, approval.id


def _world(engine: Engine, pg_url: str, *, suspicious: bool) -> Iterator[World]:
    with Session(engine) as s:
        company = Company(name="Inbox")
        s.add(company)
        s.flush()
        case_id, action_id, approval_id = _seed(s, company, suspicious=suspicious)
        s.commit()
        settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
        wf = FakeClient()
        with TestClient(create_app(settings, engine=engine, workflow_client=wf)) as client:
            yield World(client, wf, engine, company.id, case_id, action_id, approval_id)
        for model in (
            OwnerFeed, ActionRevision, UnderstandingRow, CaseLink, MessageRow, RawEvent, Approval, Send, TaskRow,
            ActionRow, CaseEvent, Case,
        ):  # fmt: skip
            s.query(model).filter(model.company_id == company.id).delete(synchronize_session=False)
        s.query(Company).filter(Company.id == company.id).delete()
        s.commit()


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    yield from _world(migrated_engine, pg_url, suspicious=False)


@pytest.fixture
def suspicious_world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    yield from _world(migrated_engine, pg_url, suspicious=True)


def _workflow_ids(w: World) -> list[str]:
    return [options["workflow_id"] for options, _args in w.wf.calls]


def _sends(w: World) -> int:
    with Session(w.engine) as s:
        return s.scalar(select(func.count()).select_from(Send).where(Send.company_id == w.company)) or 0


def _statuses(w: World) -> tuple[ApprovalStatus, ActionStatus, CaseState]:
    with Session(w.engine) as s:
        approval, action, case = s.get(Approval, w.approval), s.get(ActionRow, w.action), s.get(Case, w.case)
        assert approval is not None
        assert action is not None
        assert case is not None
        return approval.status, action.status, case.state


def test_inbox_approve_queues_the_sender_and_sends_nothing(world: World) -> None:
    r = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "d2"})
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["decision"], body["gmailMessageId"], body["whatsappMessageId"]) == (
        "approved", "execute", None, None,
    )  # fmt: skip
    assert _workflow_ids(world) == [f"exec:{world.action}:1"]
    assert _statuses(world) == (ApprovalStatus.approved, ActionStatus.approved, CaseState.waiting_on_third_party)
    assert _sends(world) == 0
    again = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "d2"})
    assert again.status_code == 200
    assert _workflow_ids(world) == [f"exec:{world.action}:1"] * 2  # same id: DBOS dedupes the replay


def test_inbox_edited_text_becomes_a_new_draft_version_first(world: World) -> None:
    r = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "edit", "edited_text": "C"})
    assert r.status_code == 200
    assert _workflow_ids(world) == [f"exec:{world.action}:2"]
    with Session(world.engine) as s:
        action = s.get(ActionRow, world.action)
        assert action is not None
        assert action.draft_version == 2


def test_inbox_reject_rejects_and_queues_nothing(world: World) -> None:
    r = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "reject"})
    assert (r.status_code, r.json()["status"]) == (200, "rejected")
    assert world.wf.calls == []
    assert _statuses(world)[:2] == (ApprovalStatus.rejected, ActionStatus.rejected)


def test_inbox_suspicious_sender_needs_confirmation(suspicious_world: World) -> None:
    w = suspicious_world
    r = w.client.post(f"/api/inbox/approvals/{w.approval}/decide", json={"choice": "d1"})
    assert r.status_code == 409
    assert w.wf.calls == []
    assert _statuses(w)[0] is ApprovalStatus.pending


def test_maintenance_approve_decides_pending_approvals_and_only_enqueues(world: World) -> None:
    r = world.client.post(f"/api/maintenance/tickets/{world.case}/approve", json={"tenantMessage": "Monteur komt"})
    assert r.status_code == 200
    assert r.json()["status"] == "authorized"
    assert _workflow_ids(world) == [f"exec:{world.action}:2"]  # the owner's tenant text is draft version 2
    assert _statuses(world)[2] is CaseState.waiting_on_third_party
    assert _sends(world) == 0

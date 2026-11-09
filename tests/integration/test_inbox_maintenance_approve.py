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

from app.api.v1.auth import Principal
from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import case_ref
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
from tests.api_auth import as_owner

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
        owner = Principal(company_id=company.id, owner_id=uuid4(), email="harjot@example.test")
        with TestClient(as_owner(create_app(settings, engine=engine, workflow_client=wf), owner)) as client:
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


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_inbox_blank_edited_text_is_refused_and_nothing_is_approved_or_queued(world: World, blank: str) -> None:
    r = world.client.post(
        f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "edit", "edited_text": blank}
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "edited_text_blank"
    assert world.wf.calls == []
    assert _statuses(world)[:2] == (ApprovalStatus.pending, ActionStatus.pending_approval)


def test_inbox_reject_ignores_blank_edited_text(world: World) -> None:
    r = world.client.post(
        f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "reject", "edited_text": " "}
    )
    assert (r.status_code, r.json()["status"]) == (200, "rejected")


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


@dataclass
class Rival:
    """Another company's pending reply: the signed-in owner of `world` must not be able to touch it."""

    company: UUID
    case: UUID
    action: UUID
    approval: UUID


@pytest.fixture
def rival(world: World) -> Iterator[Rival]:
    with Session(world.engine) as s:
        company = Company(name="Rival Inbox")
        s.add(company)
        s.flush()
        company_id = company.id
        case_id, action_id, approval_id = _seed(s, company, suspicious=False)
        s.commit()
    yield Rival(company_id, case_id, action_id, approval_id)
    with Session(world.engine) as s:
        for model in (
            OwnerFeed, ActionRevision, UnderstandingRow, CaseLink, MessageRow, RawEvent, Approval, Send, TaskRow,
            ActionRow, CaseEvent, Case,
        ):  # fmt: skip
            s.query(model).filter(model.company_id == company_id).delete(synchronize_session=False)
        s.query(Company).filter(Company.id == company_id).delete()
        s.commit()


def _rival_status(w: World, r: Rival) -> tuple[ApprovalStatus, ActionStatus]:
    with Session(w.engine) as s:
        approval, action = s.get(Approval, r.approval), s.get(ActionRow, r.action)
        assert approval is not None
        assert action is not None
        return approval.status, action.status


@pytest.mark.parametrize("ref", ["approval", "case", "action", "latest"])
def test_an_owner_cannot_decide_another_companys_approval(world: World, rival: Rival, ref: str) -> None:
    target = {"approval": rival.approval, "case": f"case-{rival.case}", "action": f"act-{rival.action}"}.get(ref, ref)
    r = world.client.post(f"/api/inbox/approvals/{target}/decide", json={"choice": "d2"})
    assert r.status_code == 404
    assert _rival_status(world, rival) == (ApprovalStatus.pending, ActionStatus.pending_approval)
    assert world.wf.calls == []


def test_latest_never_picks_a_case_for_the_owner_either(world: World) -> None:
    """Ambiguous refs are refused rather than guessed: only an approval, case or action id names a decision."""
    r = world.client.post("/api/inbox/approvals/latest/decide", json={"choice": "d2"})
    assert r.status_code == 404
    assert _statuses(world)[0] is ApprovalStatus.pending


def test_threads_and_stats_list_only_the_owners_company(world: World, rival: Rival) -> None:
    threads = world.client.get("/api/inbox/threads")
    assert threads.status_code == 200
    body = threads.text
    assert str(world.case) in body
    assert str(rival.case) not in body
    assert world.client.get("/api/inbox/stats").json()["allCount"] == threads.json()["total"] == 1


def test_create_draft_does_not_quote_another_companys_thread(world: World, rival: Rival) -> None:
    with Session(world.engine) as s:
        other_thread = s.scalars(select(MessageRow.thread_ref).where(MessageRow.company_id == rival.company)).one()
        s.query(MessageRow).filter(MessageRow.company_id == rival.company).update(
            {"meta": {"message_id": "<secret@b>"}}
        )
        s.commit()
    payload = {"to_email": "x@y.test", "subject": "Hello", "body": "b", "thread_id": other_thread}
    r = world.client.post("/api/inbox/create-draft", json=payload)
    assert r.status_code == 200
    assert "Re%3A" not in r.json()["web_url"]  # the foreign message was not quoted


# ---- maintenance tickets: the same isolation, plus honest answers when nothing matches


def _urgency(w: World, case_id: UUID) -> Urgency:
    with Session(w.engine) as s:
        case = s.get(Case, case_id)
        assert case is not None
        return case.urgency


@pytest.mark.parametrize("form", ["full", "short"])
def test_an_owner_cannot_approve_another_companys_ticket(world: World, rival: Rival, form: str) -> None:
    ref = str(rival.case) if form == "full" else case_ref(rival.case)
    r = world.client.post(f"/api/maintenance/tickets/{ref}/approve", json={})
    assert r.status_code == 404
    assert _rival_status(world, rival) == (ApprovalStatus.pending, ActionStatus.pending_approval)
    assert world.wf.calls == []


def test_approving_a_ticket_that_does_not_exist_is_a_404_not_a_fake_authorization(world: World) -> None:
    r = world.client.post(f"/api/maintenance/tickets/{uuid4()}/approve", json={})
    assert r.status_code == 404
    assert world.wf.calls == []


def test_an_owner_cannot_edit_another_companys_ticket(world: World, rival: Rival) -> None:
    r = world.client.patch(f"/api/maintenance/tickets/{rival.case}", json={"urgency": "emergency", "notes": "pwned"})
    assert r.status_code == 404
    assert _urgency(world, rival.case) is Urgency.high


def test_the_ticket_list_and_history_never_cross_companies(world: World, rival: Rival) -> None:
    listed = world.client.get("/api/maintenance/tickets")
    assert listed.status_code == 200
    assert str(rival.case) not in listed.text
    assert world.client.get(f"/api/maintenance/tickets/{rival.case}/history").status_code == 404


def test_the_history_of_an_approved_ticket_comes_from_its_persisted_events(world: World) -> None:
    assert world.client.post(f"/api/maintenance/tickets/{world.case}/approve", json={}).status_code == 200
    r = world.client.get(f"/api/maintenance/tickets/{world.case}/history")
    assert r.status_code == 200
    body = r.json()
    assert body["ticketId"] == str(world.case)
    assert body["totalEvents"] >= 1
    assert any(e["category"] == "state_change" and "→" in (e["stateChange"] or "") for e in body["events"])


def test_an_ambiguous_ticket_ref_names_nothing(world: World) -> None:
    from app.api.maintenance.routes import _find_case

    with Session(world.engine) as s:
        ids = (UUID("aaaa0000-0000-4000-8000-000000cafe01"), UUID("bbbb0000-0000-4000-8000-000000cafe01"))
        a, b = (
            Case(id=i, company_id=world.company, category=Category.maintenance, urgency=Urgency.low, summary="x")
            for i in ids
        )
        s.add_all([a, b])
        s.commit()
        try:
            assert _find_case(s, world.company, "cafe01") is None
            assert _find_case(s, world.company, "aaaa0000-0000-4000-8000-000000cafe01") is not None
            assert _find_case(s, world.company, "cafe%") is None  # LIKE wildcards are not ids
        finally:
            s.query(Case).filter(Case.id.in_([a.id, b.id])).delete(synchronize_session=False)
            s.commit()


def test_cases_created_together_get_their_own_ticket_numbers(world: World) -> None:
    from app.api.maintenance.routes import _find_case

    ids = (UUID("01a10000-0000-7000-8000-00000000d00d"), UUID("01a10000-0000-7000-8000-00000000f00d"))
    with Session(world.engine) as s:
        a, b = (
            Case(id=i, company_id=world.company, category=Category.maintenance, urgency=Urgency.low, summary="x")
            for i in ids
        )
        s.add_all([a, b])
        s.commit()
        try:
            assert case_ref(a.id) != case_ref(b.id)
            assert _find_case(s, world.company, case_ref(a.id)) == a
            assert _find_case(s, world.company, case_ref(b.id)) == b
        finally:
            s.query(Case).filter(Case.id.in_([a.id, b.id])).delete(synchronize_session=False)
            s.commit()


# ---- safe decide: repeat clicks and a paused company (moved here from mock-based unit tests)


def test_a_repeat_click_on_a_settled_approval_answers_already_decided_and_queues_nothing(world: World) -> None:
    assert (
        world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "reject"}).status_code == 200
    )
    queued_after_first = len(world.wf.calls)
    again = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "d1"})
    assert again.status_code == 200
    assert (again.json()["status"], again.json()["decision"]) == ("already_decided", "rejected")
    assert len(world.wf.calls) == queued_after_first
    assert _statuses(world)[0] is ApprovalStatus.rejected


def test_a_paused_company_holds_the_approval_and_queues_nothing(world: World) -> None:
    with Session(world.engine) as s:
        s.query(Company).filter(Company.id == world.company).update({"paused": True})
        s.commit()
    r = world.client.post(f"/api/inbox/approvals/{world.approval}/decide", json={"choice": "d1"})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["decision"]) == ("held", "paused")
    assert world.wf.calls == []
    assert _statuses(world)[1] is ActionStatus.paused
    assert _sends(world) == 0

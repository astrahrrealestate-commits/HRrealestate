"""Dashboard decision writes against real Postgres: replay safety, suspicious gate, scoping, edit, pause/resume."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.contracts import ActionType, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.db.enums import ActionStatus, ApprovalStatus, FeedKind, LinkMethod, TaskStatus
from app.db.models import (
    ActionRevision,
    ActionRow,
    Approval,
    AttachmentRow,
    Case,
    CaseLink,
    Company,
    DocumentRow,
    OwnerAccount,
    OwnerFeed,
    TaskRow,
    UnderstandingRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from app.pipeline.work_repo import short_ref

pytestmark = pytest.mark.integration
H = {CSRF_HEADER: CSRF_VALUE}
T0 = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], tuple[Any, ...]]] = []

    def enqueue(self, options: Any, *args: Any) -> Any:
        self.calls.append((options, args))

    def enqueue_in_transaction(self, conn_or_session: Any, options: Any, *args: Any) -> Any:
        raise AssertionError("not used")


@dataclass
class Side:
    company: UUID
    case: UUID
    action: UUID
    approval: UUID
    task: UUID
    attachment: UUID
    message: UUID
    bare_attachment: UUID


@dataclass
class World:
    client: TestClient
    wf: FakeClient
    a: Side
    b: Side
    engine: Engine


def _side(s: Session, company: Company, tag: str, *, suspicious: bool) -> Side:
    case = Case(company_id=company.id, category=Category.other, urgency=Urgency.high, summary=tag)
    s.add(case)
    s.flush()
    action = ActionRow(
        company_id=company.id, case_id=case.id, type=ActionType.reply_draft, payload={"body_variants": ["x"]},
        rationale="r", context_ref=[], status=ActionStatus.pending_approval,
    )  # fmt: skip
    task = TaskRow(company_id=company.id, case_id=case.id, title=f"t {tag}", assignee="owner", source="owner")
    raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=f"m-{tag}-{uuid4()}", payload={})
    s.add_all([action, task, raw])
    s.flush()
    msg = MessageRow(company_id=company.id, raw_event_id=raw.id, channel=Channel.gmail,
                     provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="x@y.test",
                     direction=Direction.inbound, sent_at=T0, text="hi")  # fmt: skip
    s.add(msg)
    s.flush()
    approval = Approval(company_id=company.id, action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
    att = AttachmentRow(company_id=company.id, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                        filename="a.pdf", size_bytes=1, sha256="0" * 64)  # fmt: skip
    s.add_all(
        [approval, att, CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread)]
    )
    s.add(UnderstandingRow(company_id=company.id, message_id=msg.id, category=Category.other, urgency=Urgency.high,
                           body={"suspicious": {"flag": suspicious}}, prompt_version="understanding/v2"))  # fmt: skip
    bare = AttachmentRow(company_id=company.id, message_id=msg.id, s3_key="k2", mime_type="application/pdf",
                         filename="b.pdf", size_bytes=1, sha256="1" * 64)  # fmt: skip
    s.add(bare)
    s.flush()
    action.context_ref = [msg.id]
    s.add(DocumentRow(company_id=company.id, attachment_id=att.id, doc_type="lease", title="t", file_name="a.pdf",
                      confidence=0.9))  # fmt: skip
    s.flush()
    return Side(company.id, case.id, action.id, approval.id, task.id, att.id, msg.id, bare.id)


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        ca, cb = Company(name="A"), Company(name="B")
        s.add_all([ca, cb])
        s.flush()
        owner = OwnerAccount(company_id=ca.id, display_name="H", whatsapp_e164="+31699999996", email="h@a.test")
        s.add(owner)
        a, b = _side(s, ca, "a", suspicious=True), _side(s, cb, "b", suspicious=False)
        s.commit()
        settings = Settings(
            database_url=pg_url,  # type: ignore[arg-type]
            env="test",
            dashboard_session_secret=SecretStr("x" * 32),
            _env_file=None,
        )
        principal = Principal(company_id=ca.id, owner_id=owner.id, email="h@a.test")
        wf = FakeClient()
        with TestClient(create_app(settings, engine=migrated_engine, workflow_client=wf)) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, wf, a, b, migrated_engine)
        ids = [ca.id, cb.id]
        for model in (
            OwnerFeed, DocumentRow, ActionRevision, UnderstandingRow, CaseLink, AttachmentRow, MessageRow,
            RawEvent, Approval, TaskRow, ActionRow, Case,
        ):  # fmt: skip
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(OwnerAccount).filter(OwnerAccount.id == owner.id).delete()
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def _decide(w: World, approval: UUID, choice: str = "ok", **extra: Any) -> Any:
    return w.client.post(f"/api/v1/approvals/{approval}/decide", json={"choice": choice, **extra}, headers=H)


def test_suspicious_needs_confirm_then_executes_once(world: World) -> None:
    r = _decide(world, world.a.approval)
    assert (r.status_code, r.json()["detail"]) == (409, "confirm_suspicious_required")
    assert world.wf.calls == []
    r = _decide(world, world.a.approval, confirm_suspicious=True)
    assert r.json()["kind"] == "execute"
    assert [c[0]["workflow_id"] for c in world.wf.calls] == [f"exec:{world.a.action}:1"]
    with Session(world.engine) as s:
        assert s.scalar(select(ActionRow.status).where(ActionRow.id == world.a.action)) is ActionStatus.approved


def test_reject_never_needs_confirm_and_never_enqueues(world: World) -> None:
    r = _decide(world, world.a.approval, "rej")
    assert r.json()["kind"] == "rejected"
    assert world.wf.calls == []


def test_second_decide_returns_first_and_does_not_enqueue_a_different_decision(world: World) -> None:
    first = _decide(world, world.a.approval, "d2", confirm_suspicious=True).json()
    second = _decide(world, world.a.approval, "rej", confirm_suspicious=True).json()
    assert second == first
    assert {c[0]["workflow_id"] for c in world.wf.calls} == {f"exec:{world.a.action}:1"}  # DBOS dedupes same id


def test_not_suspicious_executes_without_confirm(world: World) -> None:
    with Session(world.engine) as s:
        s.query(UnderstandingRow).filter(UnderstandingRow.company_id == world.a.company).update(
            {"body": {"suspicious": {"flag": False}}}
        )
        s.commit()
    assert _decide(world, world.a.approval).json()["kind"] == "execute"


def test_foreign_and_random_approval_share_one_404(world: World) -> None:
    foreign, missing = _decide(world, world.b.approval), _decide(world, uuid4())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert world.wf.calls == []


def test_stale_version_is_200_with_flag(world: World) -> None:
    with Session(world.engine) as s:
        s.query(ActionRow).filter(ActionRow.id == world.a.action).update({"draft_version": 2})
        s.commit()
    r = _decide(world, world.a.approval, confirm_suspicious=True)
    assert (r.status_code, r.json()["kind"], r.json()["stale"]) == (200, "stale", True)
    assert world.wf.calls == []


def test_decide_resolves_the_feed_row_company_scoped(world: World) -> None:
    with Session(world.engine) as s:
        s.add_all(
            [
                OwnerFeed(company_id=world.a.company, idempotency_key=f"f-{uuid4()}", kind=FeedKind.approval,
                          ref_id=world.a.approval, payload={}),
                OwnerFeed(company_id=world.b.company, idempotency_key=f"f-{uuid4()}", kind=FeedKind.approval,
                          ref_id=world.a.approval, payload={}),
            ]
        )  # fmt: skip
        s.commit()
    _decide(world, world.a.approval, "rej")
    with Session(world.engine) as s:
        rows = s.scalars(select(OwnerFeed).where(OwnerFeed.ref_id == world.a.approval)).all()
    assert {r.company_id: r.resolved_at is not None for r in rows} == {world.a.company: True, world.b.company: False}


def test_edit_creates_next_version_and_new_approval(world: World) -> None:
    r = world.client.post(f"/api/v1/approvals/{world.a.approval}/edit", json={"text": "nieuwe tekst"}, headers=H)
    assert r.status_code == 200
    assert r.json()["draft_version"] == 2
    with Session(world.engine) as s:
        action = s.scalars(select(ActionRow).where(ActionRow.id == world.a.action)).one()
        new = s.scalars(select(Approval).where(Approval.id == UUID(r.json()["approval_id"]))).one()
    assert action.payload["body_variants"] == ["nieuwe tekst"]
    assert (new.draft_version, new.status) == (2, ApprovalStatus.pending)
    again = world.client.post(f"/api/v1/approvals/{world.a.approval}/edit", json={"text": "nog een"}, headers=H)
    assert again.status_code == 409


def test_edit_foreign_approval_404(world: World) -> None:
    r = world.client.post(f"/api/v1/approvals/{world.b.approval}/edit", json={"text": "x"}, headers=H)
    assert r.status_code == 404


def test_task_done_and_snooze_scoped(world: World) -> None:
    ref = short_ref(world.a.task)
    assert world.client.post(f"/api/v1/tasks/{ref}/snooze", json={"duration": "4h"}, headers=H).status_code == 204
    with Session(world.engine) as s:
        task = s.scalars(select(TaskRow).where(TaskRow.id == world.a.task)).one()
        assert task.status is TaskStatus.snoozed
        assert task.snoozed_until is not None
        assert task.snoozed_until > datetime.now(UTC) + timedelta(hours=3)
    assert world.client.post(f"/api/v1/tasks/{ref}/done", headers=H).status_code == 204
    foreign = world.client.post(f"/api/v1/tasks/{short_ref(world.b.task)}/done", headers=H)
    assert foreign.status_code == 404
    bad = world.client.post(f"/api/v1/tasks/{ref}/snooze", json={"duration": "forever"}, headers=H)
    assert bad.status_code == 422


def test_document_file_scoped_and_validated(world: World) -> None:
    ok = world.client.post(f"/api/v1/documents/{world.a.attachment}/file", json={"choice": "lease"}, headers=H)
    assert ok.status_code == 202
    assert world.wf.calls[0][0]["workflow_id"] == f"doc:{world.a.attachment}:owner:lease"
    foreign = world.client.post(f"/api/v1/documents/{world.b.attachment}/file", json={"choice": "lease"}, headers=H)
    assert foreign.status_code == 404
    bad = world.client.post(f"/api/v1/documents/{world.a.attachment}/file", json={"choice": "nope"}, headers=H)
    assert bad.status_code == 422
    assert len(world.wf.calls) == 1


def test_pause_resume_flag_and_reenqueue(world: World) -> None:
    assert world.client.post("/api/v1/company/pause", headers=H).json() == {"paused": True}
    assert world.client.get("/api/v1/company").json()["paused"] is True
    with Session(world.engine) as s:
        s.query(ActionRow).filter(ActionRow.id == world.a.action).update({"status": ActionStatus.approved})
        s.query(Approval).filter(Approval.id == world.a.approval).update({"status": ApprovalStatus.approved})
        s.commit()
    assert world.client.post("/api/v1/company/resume", headers=H).json() == {"paused": False}
    assert world.client.get("/api/v1/company").json()["paused"] is False
    assert [c[0]["workflow_id"].startswith(f"exec:{world.a.action}:1:resume:") for c in world.wf.calls] == [True]
    world.client.post("/api/v1/company/resume", headers=H)  # not paused any more: still re-enqueues, new suffix
    ids = [c[0]["workflow_id"] for c in world.wf.calls]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(i.startswith(f"exec:{world.a.action}:1:resume:") for i in ids)
    with Session(world.engine) as s:
        assert s.scalar(select(Company.paused).where(Company.id == world.b.company)) is False


def _newer_harmless_message(w: World) -> None:
    with Session(w.engine) as s:
        raw = RawEvent(company_id=w.a.company, provider=Channel.gmail, provider_msg_id=f"n-{uuid4()}", payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(company_id=w.a.company, raw_event_id=raw.id, channel=Channel.gmail,
                         provider_msg_id=raw.provider_msg_id, thread_ref="t", sender_identity="x@y.test",
                         direction=Direction.inbound, sent_at=T0 + timedelta(hours=1), text="ok")  # fmt: skip
        s.add(msg)
        s.flush()
        s.add_all([
            CaseLink(company_id=w.a.company, case_id=w.a.case, message_id=msg.id, method=LinkMethod.thread),
            UnderstandingRow(company_id=w.a.company, message_id=msg.id, category=Category.other, urgency=Urgency.high,
                             body={"suspicious": {"flag": False}}, prompt_version="understanding/v2"),
        ])  # fmt: skip
        s.commit()


def test_newer_harmless_message_cannot_bypass_the_gate(world: World) -> None:
    _newer_harmless_message(world)
    r = _decide(world, world.a.approval)
    assert (r.status_code, r.json()["detail"]) == (409, "confirm_suspicious_required")
    assert world.wf.calls == []


def test_empty_context_ref_falls_back_to_any_flagged_on_case(world: World) -> None:
    _newer_harmless_message(world)
    with Session(world.engine) as s:
        s.query(ActionRow).filter(ActionRow.id == world.a.action).update({"context_ref": []})
        s.commit()
    assert _decide(world, world.a.approval).status_code == 409
    assert world.wf.calls == []


def test_replay_of_approved_suspicious_returns_first_decision(world: World) -> None:
    first = _decide(world, world.a.approval, confirm_suspicious=True)
    replay = _decide(world, world.a.approval)
    assert replay.status_code == 200
    assert replay.json() == first.json()


def test_edit_after_approval_is_409_and_enqueues_nothing(world: World) -> None:
    _decide(world, world.a.approval, confirm_suspicious=True)
    world.wf.calls.clear()
    r = world.client.post(f"/api/v1/approvals/{world.a.approval}/edit", json={"text": "late"}, headers=H)
    assert r.status_code == 409
    assert world.wf.calls == []


def test_deciding_the_old_approval_after_an_edit_returns_edit_without_enqueue(world: World) -> None:
    world.client.post(f"/api/v1/approvals/{world.a.approval}/edit", json={"text": "new"}, headers=H)
    r = _decide(world, world.a.approval, confirm_suspicious=True)
    assert r.json()["kind"] == "edit"
    assert world.wf.calls == []


def test_decide_edit_choice_is_422(world: World) -> None:
    assert _decide(world, world.a.approval, "edit").status_code == 422


def test_done_twice_is_idempotent(world: World) -> None:
    ref = short_ref(world.a.task)
    assert world.client.post(f"/api/v1/tasks/{ref}/done", headers=H).status_code == 204
    assert world.client.post(f"/api/v1/tasks/{ref}/done", headers=H).status_code == 204


def test_task_ref_wildcards_rejected(world: World) -> None:
    assert world.client.post("/api/v1/tasks/%25%25%25%25%25%25/done", headers=H).status_code == 422


def test_attachment_without_document_row_404(world: World) -> None:
    r = world.client.post(f"/api/v1/documents/{world.a.bare_attachment}/file", json={"choice": "lease"}, headers=H)
    assert r.status_code == 404
    assert world.wf.calls == []


def test_resume_when_not_paused_still_reenqueues_approved(world: World) -> None:
    with Session(world.engine) as s:
        s.query(ActionRow).filter(ActionRow.id == world.a.action).update({"status": ActionStatus.approved})
        s.query(Approval).filter(Approval.id == world.a.approval).update({"status": ApprovalStatus.approved})
        s.commit()
    assert world.client.post("/api/v1/company/resume", headers=H).status_code == 200
    assert len(world.wf.calls) == 1

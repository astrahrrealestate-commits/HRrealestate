"""Owner reply → decision → `exec:{action_id}:{version}` → exactly one Gmail draft; edit flow; local actions."""

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, ButtonChoice, ButtonId, CaseState, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import ActionStatus, LinkMethod, PersonKind
from app.db.models import (
    ActionRow,
    Case,
    ChannelAccount,
    Company,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    Send,
    TaskRow,
)
from app.pipeline import approvals, case_repo
from app.sender.execute import SenderDeps
from app.workflows import actions, owner_reply
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
MAILBOX, OWNER = "beheer@example.test", "+31600000100"
REPLY = {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["Optie A", "Optie B"]}


@dataclass
class Env:
    engine: Engine
    company_id: UUID
    case_id: UUID
    wa: FakeWhatsAppOutbound
    drafts: FakeDrafts


def _raw(s: Session, cid: UUID, channel: Channel) -> RawEvent:
    raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    return raw


@pytest.fixture
def env(test_settings: Settings, migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        s.add_all(
            [
                ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX),
                OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164=OWNER),
            ]
        )
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()
        raw = _raw(s, cid, Channel.gmail)
        msg = MessageRow(
            company_id=cid,
            raw_event_id=raw.id,
            channel=Channel.gmail,
            provider_msg_id=raw.provider_msg_id,
            thread_ref="thr-1",
            sender_identity="sanne@example.test",
            direction=Direction.inbound,
            sent_at=NOW,
            text="Lekkage",
            person_id=person.id,
            meta={"subject": "Lekkage"},
        )
        s.add(msg)
        s.flush()
        case_id = case_repo.create_case(s, cid, person.id, Category.maintenance, Urgency.high)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        s.commit()
    wa, drafts = FakeWhatsAppOutbound(), FakeDrafts(FakeMailbox(MAILBOX, MemoryMailboxStore()))
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    set_sender_deps(SenderDeps(migrated_engine, wa, lambda _a: drafts))
    yield Env(migrated_engine, cid, case_id, wa, drafts)
    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


def _pending(env: Env, kind: ActionType = ActionType.reply_draft, payload: dict[str, Any] = REPLY) -> UUID:
    with Session(env.engine) as s:
        a = ActionRow(
            company_id=env.company_id,
            case_id=env.case_id,
            type=kind,
            payload=payload,
            rationale="r",
            context_ref=[],
            status=ActionStatus.pending_approval,
        )
        s.add(a)
        s.flush()
        approval_id = approvals.open_approval(s, env.company_id, a.id, 1, urgency=Urgency.normal, now=NOW)
        s.commit()
        return approval_id


def _owner_msg(env: Env, text: str, interactive_id: str | None = None) -> UUID:
    with Session(env.engine) as s:
        raw = _raw(s, env.company_id, Channel.whatsapp)
        meta = {"type": "interactive"} | ({"interactive_id": interactive_id} if interactive_id else {})
        m = MessageRow(
            company_id=env.company_id,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=raw.provider_msg_id,
            thread_ref=OWNER,
            sender_identity=OWNER,
            direction=Direction.inbound,
            sent_at=NOW,
            text=text,
            meta=meta,
        )
        s.add(m)
        s.commit()
        return m.id


def _wait_for(workflow_id: str) -> Any:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = DBOS.retrieve_workflow(workflow_id).get_status()
        if status.status not in ("ENQUEUED", "PENDING"):
            assert status.status == "SUCCESS", f"{workflow_id}: {status.status} {status.error}"
            return status.output
        time.sleep(0.1)
    raise AssertionError(f"{workflow_id} did not finish")


def test_tap_d2_twice_creates_exactly_one_draft(env: Env) -> None:
    approval_id = _pending(env)
    button = ButtonId(approval_id=approval_id, choice=ButtonChoice.d2).render()
    for _ in range(2):
        mid = _owner_msg(env, "Send draft 2", button)
        DBOS.start_workflow(owner_reply.owner_reply, str(mid)).get_result()
    with Session(env.engine) as s:
        action_id = s.scalar(select(ActionRow.id).where(ActionRow.case_id == env.case_id))
    assert _wait_for(f"exec:{action_id}:1") in ("sent", "already")
    assert [r.body for r in env.drafts.created] == ["Optie B"]


def test_edit_then_text_sends_new_approval_prompt(env: Env) -> None:
    approval_id = _pending(env)
    tap = _owner_msg(env, "Edit", ButtonId(approval_id=approval_id, choice=ButtonChoice.edit).render())
    assert DBOS.start_workflow(owner_reply.owner_reply, str(tap)).get_result() == "edit"
    text = _owner_msg(env, "Beste Sanne, de loodgieter komt morgen.")
    assert DBOS.start_workflow(owner_reply.owner_reply, str(text)).get_result() == "revision"
    with Session(env.engine) as s:
        action = s.scalar(select(ActionRow).where(ActionRow.case_id == env.case_id))
        assert action is not None
        assert action.draft_version == 2
    bodies = [m.payload.get("text", {}).get("body", "") + str(m.payload.get("interactive", "")) for m in env.wa.sent]
    assert any("loodgieter komt morgen" in b for b in bodies)


def test_reject_closes_task_and_sends_nothing(env: Env) -> None:
    approval_id = _pending(env)
    tap = _owner_msg(env, "Reject", ButtonId(approval_id=approval_id, choice=ButtonChoice.rej).render())
    assert DBOS.start_workflow(owner_reply.owner_reply, str(tap)).get_result() == "rejected"
    with Session(env.engine) as s:
        assert (
            s.scalar(
                select(func.count())
                .select_from(Send)
                .where(Send.action_id.is_not(None), Send.company_id == env.company_id)
            )
            == 0
        )


def test_local_actions_apply_without_sending(env: Env) -> None:
    approval_id = _pending(env, ActionType.update_case_state, {"kind": "update_case_state", "new_state": "resolved"})
    tap = _owner_msg(env, "Approve", ButtonId(approval_id=approval_id, choice=ButtonChoice.ok).render())
    DBOS.start_workflow(owner_reply.owner_reply, str(tap)).get_result()
    with Session(env.engine) as s:
        action_id = s.scalar(select(ActionRow.id).where(ActionRow.case_id == env.case_id))
    assert _wait_for(f"exec:{action_id}:1") == "applied"
    with Session(env.engine) as s:
        assert s.scalar(select(Case.state).where(Case.id == env.case_id)) is CaseState.resolved
    reminder = {"kind": "create_reminder", "due_at": "2026-10-09T08:00:00+00:00", "note": "Bel loodgieter"}
    approval_id = _pending(env, ActionType.create_reminder, reminder)
    tap = _owner_msg(env, "Approve", ButtonId(approval_id=approval_id, choice=ButtonChoice.ok).render())
    DBOS.start_workflow(owner_reply.owner_reply, str(tap)).get_result()
    with Session(env.engine) as s:
        reminder_action = s.scalar(
            select(ActionRow.id).where(
                ActionRow.type == ActionType.create_reminder, ActionRow.company_id == env.company_id
            )
        )
    assert _wait_for(f"exec:{reminder_action}:1") == "applied"
    with Session(env.engine) as s:
        assert (
            s.scalar(select(TaskRow.title).where(TaskRow.source == "reminder", TaskRow.company_id == env.company_id))
            == "Bel loodgieter"
        )
    assert actions.EXECUTE_ACTION == "actions.execute_action"

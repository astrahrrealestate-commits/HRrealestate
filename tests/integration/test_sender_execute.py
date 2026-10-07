"""Sender guards and effects: approval + version + pause re-checked, idempotent sends, Phase 1 allowlist."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import FakeDrafts
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, ButtonChoice, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, LinkMethod, PersonKind, SendStatus
from app.db.models import ActionRow, ChannelAccount, Company, MessageRow, OwnerAccount, Person, RawEvent, Send
from app.pipeline import approvals, case_repo
from app.sender.execute import SenderDeps, execute_action, send_to_owner

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
MAILBOX, OWNER, TENANT = "beheer@example.test", "+31600000100", "sanne@example.test"


@dataclass
class Env:
    engine: Engine
    company_id: UUID
    case_id: UUID
    deps: SenderDeps
    wa: FakeWhatsAppOutbound
    drafts: FakeDrafts


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    cid = committed_company.id
    with Session(migrated_engine, expire_on_commit=False) as s:
        s.add_all([
            ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX),
            OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164=OWNER),
        ])  # fmt: skip
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id="gm-1", payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id="gm-1", thread_ref="thr-1",
            sender_identity=TENANT, direction=Direction.inbound, sent_at=NOW, text="Lekkage", person_id=person.id,
            meta={"subject": "Lekkage badkamer", "message_id": "<m1@example.test>"},
        )  # fmt: skip
        s.add(msg)
        s.flush()
        case_id = case_repo.create_case(s, cid, person.id, Category.maintenance, Urgency.high)
        case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        s.commit()
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    wa, drafts = FakeWhatsAppOutbound(), FakeDrafts(mailbox)
    return Env(migrated_engine, cid, case_id, SenderDeps(migrated_engine, wa, lambda _addr: drafts), wa, drafts)


def _approved(env: Env, kind: ActionType, payload: dict, choice: ButtonChoice = ButtonChoice.d2) -> UUID:  # type: ignore[type-arg]
    with Session(env.engine) as s:
        a = ActionRow(company_id=env.company_id, case_id=env.case_id, type=kind, payload=payload, rationale="r",
                      context_ref=[], status=ActionStatus.pending_approval)  # fmt: skip
        s.add(a)
        s.flush()
        aid = approvals.open_approval(s, env.company_id, a.id, 1, urgency=Urgency.normal, now=NOW)
        approvals.decide(s, env.company_id, aid, choice, at=NOW)
        s.commit()
        return a.id


REPLY = {"kind": "reply_draft", "channel": "gmail", "subject": None, "body_variants": ["Optie A", "Optie B"]}


def test_gmail_reply_creates_one_draft_in_thread_with_chosen_variant(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    first = execute_action(env.deps, action_id, 1)
    second = execute_action(env.deps, action_id, 1)
    assert (first.status, second.status) == ("sent", "already")
    assert len(env.drafts.created) == 1
    req = env.drafts.created[0]
    assert (req.thread_id, req.to, req.body, req.subject, req.in_reply_to) == (
        "thr-1", TENANT, "Optie B", "Re: Lekkage badkamer", "<m1@example.test>"
    )  # fmt: skip
    assert env.wa.sent == []
    with Session(env.engine) as s:
        assert s.scalar(select(ActionRow.status).where(ActionRow.id == action_id)) is ActionStatus.executed
        send = s.scalar(select(Send).where(Send.action_id == action_id))
        assert send is not None
        assert (send.status, send.idempotency_key, send.channel) == (
            SendStatus.sent,
            f"exec:{action_id}:1",
            Channel.gmail,
        )


def test_whatsapp_reply_goes_to_owner_never_to_tenant(env: Env) -> None:
    payload = {**REPLY, "channel": "whatsapp"}
    action_id = _approved(env, ActionType.reply_draft, payload, ButtonChoice.d1)
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [m.payload["to"] for m in env.wa.sent] == [OWNER.removeprefix("+")]
    assert "Optie A" in env.wa.sent[0].payload["text"]["body"]


def test_unapproved_wrong_version_and_paused_are_blocked(env: Env) -> None:
    with Session(env.engine) as s:
        a = ActionRow(company_id=env.company_id, case_id=env.case_id, type=ActionType.reply_draft, payload=REPLY,
                      rationale="r", context_ref=[], status=ActionStatus.pending_approval)  # fmt: skip
        s.add(a)
        s.commit()
        pending_id = a.id
    assert execute_action(env.deps, pending_id, 1).status == "blocked"
    approved = _approved(env, ActionType.reply_draft, REPLY)
    assert execute_action(env.deps, approved, 2).status == "blocked"
    with Session(env.engine) as s:
        company = s.get(Company, env.company_id)
        assert company is not None
        company.paused = True
        s.commit()
    assert execute_action(env.deps, approved, 1).status == "blocked"
    assert env.drafts.created == []
    with Session(env.engine) as s:
        assert s.scalar(select(func.count()).select_from(Send).where(Send.company_id == env.company_id)) == 0


def test_notify_owner_and_send_to_owner_are_idempotent(env: Env) -> None:
    action_id = _approved(env, ActionType.notify_owner, {"kind": "notify_owner", "text": "Lekkage gemeld"},
                          ButtonChoice.ok)  # fmt: skip
    execute_action(env.deps, action_id, 1)
    key = f"owner:{new_id()}"
    ref1 = send_to_owner(env.deps, env.company_id, key, lambda to: {"messaging_product": "whatsapp", "to": to,
                         "type": "text", "text": {"body": "hi"}})  # fmt: skip
    ref2 = send_to_owner(env.deps, env.company_id, key, lambda to: {"never": "built"})
    assert ref1 == ref2
    assert len(env.wa.sent) == 2

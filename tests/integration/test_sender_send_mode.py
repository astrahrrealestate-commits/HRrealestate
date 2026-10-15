"""Send mode (spec §5): an approved reply reaches the case contact, and only under every guard."""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.channels.gmail.drafts import FakeDrafts, GmailDraftError
from app.channels.gmail.fake import FakeMailbox, MemoryMailboxStore
from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, ButtonChoice, Category, Channel, Direction, OutboundMode, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, FeedKind, LinkMethod, PersonKind, SendStatus
from app.db.models import (
    ActionRow,
    ChannelAccount,
    ChannelIdentity,
    Company,
    MessageRow,
    OwnerAccount,
    OwnerFeed,
    Person,
    RawEvent,
    Send,
)
from app.pipeline import approvals, case_repo
from app.sender.execute import SenderDeps, execute_action
from app.sender.plan import Plan
from app.sender.targets import SendBlockedError, assert_allowed, plan_for
from app.sender.tenant_gate import CAP_REACHED, GMAIL_SEND_MISSING

pytestmark = pytest.mark.integration
MAILBOX, OWNER, OWNER_MAIL = "beheer@example.test", "+31600000100", "harjot@example.test"
TENANT_MAIL, TENANT_NR, VALID_FROM = "sanne@example.test", "+31612345678", date(2026, 1, 1)
REPLY: dict[str, Any] = {
    "kind": "reply_draft",
    "channel": "gmail",
    "subject": None,
    "body_variants": ["Optie A", "Optie B"],
}


@dataclass
class Env:
    engine: Engine
    company_id: UUID
    case_id: UUID
    deps: SenderDeps
    wa: FakeWhatsAppOutbound
    drafts: FakeDrafts
    replies: FakeDrafts


def _inbound(s: Session, cid: UUID, person_id: UUID, channel: Channel, sender: str, at: datetime) -> MessageRow:
    raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=f"in-{new_id()}", payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
        thread_ref="thr-1" if channel is Channel.gmail else sender, sender_identity=sender,
        direction=Direction.inbound, sent_at=at, created_at=at, text="Lekkage", person_id=person_id,
        meta={"subject": "Lekkage badkamer", "message_id": "<m1@example.test>", "mailbox": MAILBOX},
    )  # fmt: skip
    s.add(msg)
    s.flush()
    return msg


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    cid, recent = committed_company.id, datetime.now(UTC) - timedelta(hours=1)
    with Session(migrated_engine) as s:
        s.execute(update(Company).where(Company.id == cid).values(outbound_mode=OutboundMode.send))
        owner = OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164=OWNER, email=OWNER_MAIL)
        s.add_all([ChannelAccount(company_id=cid, channel=Channel.gmail, address=MAILBOX), owner])
        person = Person(company_id=cid, kind=PersonKind.tenant, display_name="Sanne", valid_from=VALID_FROM)
        s.add(person)
        s.flush()
        for channel, identity in ((Channel.gmail, TENANT_MAIL), (Channel.whatsapp, TENANT_NR)):
            s.add(ChannelIdentity(company_id=cid, person_id=person.id, channel=channel, identity=identity,
                                  valid_from=VALID_FROM))  # fmt: skip
        case_id = case_repo.create_case(s, cid, person.id, Category.maintenance, Urgency.high)
        for channel, sender in ((Channel.gmail, "Sanne@Example.TEST"), (Channel.whatsapp, TENANT_NR)):
            msg = _inbound(s, cid, person.id, channel, sender, recent)
            case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.new_case, None)
        s.commit()
    mailbox = FakeMailbox(MAILBOX, MemoryMailboxStore())
    wa, drafts, replies = FakeWhatsAppOutbound(), FakeDrafts(mailbox), FakeDrafts(mailbox)
    deps = SenderDeps(migrated_engine, wa, lambda _a: drafts, gmail_sender=lambda _a: replies)
    return Env(migrated_engine, cid, case_id, deps, wa, drafts, replies)


def _approved(env: Env, kind: ActionType, payload: dict[str, Any], choice: ButtonChoice = ButtonChoice.d2) -> UUID:
    with Session(env.engine) as s:
        a = ActionRow(company_id=env.company_id, case_id=env.case_id, type=kind, payload=payload, rationale="r",
                      context_ref=[], status=ActionStatus.pending_approval)  # fmt: skip
        s.add(a)
        s.flush()
        aid = approvals.open_approval(s, env.company_id, a.id, 1, urgency=Urgency.normal, now=datetime.now(UTC))
        approvals.decide(s, env.company_id, aid, choice, at=datetime.now(UTC))
        s.commit()
        return a.id


def _set(env: Env, model: Any, **values: Any) -> None:
    with Session(env.engine) as s, s.begin():
        s.execute(update(model).where(model.company_id == env.company_id).values(**values))


def _set_company(env: Env, **values: Any) -> None:
    with Session(env.engine) as s, s.begin():
        s.execute(update(Company).where(Company.id == env.company_id).values(**values))


def _alert(env: Env, action_id: UUID) -> OwnerFeed | None:
    key = feed.stored_key(env.company_id, f"blocked:{action_id}:1")
    with Session(env.engine) as s:
        return s.scalar(
            select(OwnerFeed).where(OwnerFeed.company_id == env.company_id, OwnerFeed.idempotency_key == key)
        )


def _sends(env: Env) -> int:
    with Session(env.engine) as s:
        return int(s.scalar(select(func.count()).select_from(Send).where(Send.company_id == env.company_id)) or 0)


def _assert_blocked(env: Env, action_id: UUID, reason: str) -> None:
    outcome = execute_action(env.deps, action_id, 1)
    assert outcome.status == "blocked"
    assert reason in (outcome.reason or "")
    assert (env.wa.sent, env.drafts.created, env.replies.replies) == ([], [], [])
    alert = _alert(env, action_id)
    assert alert is not None
    assert alert.kind is FeedKind.alert
    assert reason in alert.payload["text"]
    assert "Optie" not in alert.payload["text"]  # the reason only, never the message body


def test_draft_mode_still_creates_a_gmail_draft(env: Env) -> None:
    _set_company(env, outbound_mode=OutboundMode.draft)
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [r.body for r in env.drafts.created] == ["Optie B"]
    assert env.replies.replies == []


def test_send_mode_gmail_sends_one_reply_to_the_canonical_contact(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    first = execute_action(env.deps, action_id, 1)
    assert (first.status, execute_action(env.deps, action_id, 1).status) == ("sent", "already")
    [req] = env.replies.replies
    assert (req.to, req.thread_id, req.body, req.in_reply_to) == (TENANT_MAIL, "thr-1", "Optie B", "<m1@example.test>")
    assert env.drafts.created == []
    with Session(env.engine) as s:
        send = s.scalar(select(Send).where(Send.action_id == action_id))
        assert send is not None
        assert (send.status, send.channel, send.target, send.provider_ref) == (
            SendStatus.sent, Channel.gmail, TENANT_MAIL, first.provider_ref)  # fmt: skip
        assert s.scalar(select(ActionRow.status).where(ActionRow.id == action_id)) is ActionStatus.executed
    assert _alert(env, action_id) is None


def test_send_mode_whatsapp_in_window_texts_the_contact(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, {**REPLY, "channel": "whatsapp"}, ButtonChoice.d1)
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [(m.payload["to"], m.payload["text"]["body"]) for m in env.wa.sent] == [(TENANT_NR[1:], "Optie A")]


def test_whatsapp_window_closed_is_blocked_with_zero_calls(env: Env) -> None:
    old = datetime.now(UTC) - timedelta(hours=30)
    _set(env, MessageRow, sent_at=old, created_at=old)
    action_id = _approved(env, ActionType.reply_draft, {**REPLY, "channel": "whatsapp"})
    _assert_blocked(env, action_id, "WhatsApp window closed")
    assert _sends(env) == 0


def test_a_sender_that_is_no_longer_the_contacts_identity_is_blocked(env: Env) -> None:
    _set(env, ChannelIdentity, valid_to=datetime.now(UTC).date() - timedelta(days=1))
    _assert_blocked(env, _approved(env, ActionType.reply_draft, REPLY), "no inbound message from the case contact")


def test_paused_company_is_blocked_and_told(env: Env) -> None:
    _set_company(env, paused=True)
    _assert_blocked(env, _approved(env, ActionType.reply_draft, REPLY), "company paused")


def test_reply_edited_after_approval_is_blocked(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    with Session(env.engine) as s, s.begin():
        s.execute(update(ActionRow).where(ActionRow.id == action_id).values(draft_version=2))
    _assert_blocked(env, action_id, "draft version superseded")


def test_missing_gmail_send_token_blocks_and_never_falls_back_to_a_draft(env: Env) -> None:
    env.deps = replace(env.deps, gmail_sender=None)
    _assert_blocked(env, _approved(env, ActionType.reply_draft, REPLY), GMAIL_SEND_MISSING)
    assert _sends(env) == 0


def _prior_send(env: Env, target: str) -> None:
    with Session(env.engine) as s, s.begin():
        s.add(Send(company_id=env.company_id, idempotency_key=f"prior:{new_id()}", channel=Channel.whatsapp,
                   target=target, status=SendStatus.sent))  # fmt: skip


def test_hourly_cap_blocks_tenant_sends(env: Env) -> None:
    env.deps = replace(env.deps, tenant_sends_per_hour=1)
    _prior_send(env, "+31699999999")
    _assert_blocked(env, _approved(env, ActionType.reply_draft, REPLY), CAP_REACHED)


def test_owner_messages_do_not_count_against_the_cap(env: Env) -> None:
    env.deps = replace(env.deps, tenant_sends_per_hour=1)
    _prior_send(env, OWNER)
    assert execute_action(env.deps, _approved(env, ActionType.reply_draft, REPLY), 1).status == "sent"


def test_ambiguous_gmail_failure_is_failed_not_retried_and_told(env: Env) -> None:
    calls: list[Any] = []

    def broken(request: Any) -> str:
        calls.append(request)
        raise GmailDraftError("sending reply failed: HTTP 503", retryable=False, maybe_sent=True)

    env.replies.send_reply = broken  # type: ignore[method-assign]
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    outcome = execute_action(env.deps, action_id, 1)
    assert outcome.status == "failed"
    assert "may have been delivered" in (outcome.reason or "")
    assert execute_action(env.deps, action_id, 1).status == "blocked"  # a failed action is never re-sent blindly
    assert len(calls) == 1
    alert = _alert(env, action_id)
    assert alert is not None
    assert "may have been delivered" in alert.payload["text"]
    with Session(env.engine) as s:
        assert s.scalar(select(ActionRow.status).where(ActionRow.id == action_id)) is ActionStatus.failed
        assert s.scalar(select(Send.status).where(Send.action_id == action_id)) is SendStatus.failed


def _contractor(env: Env) -> str:
    with Session(env.engine) as s, s.begin():
        person = Person(company_id=env.company_id, kind=PersonKind.contractor, display_name="Jansen",
                        valid_from=VALID_FROM)  # fmt: skip
        s.add(person)
        s.flush()
        s.add(ChannelIdentity(company_id=env.company_id, person_id=person.id, channel=Channel.whatsapp,
                              identity="+31688888888", valid_from=VALID_FROM))  # fmt: skip
        return str(person.id)


def test_contractor_requests_and_escalations_stay_with_the_owner_in_send_mode(env: Env) -> None:
    request = {"kind": "request_contractor", "contractor_person_id": _contractor(env), "body_variants": ["A", "B"]}
    escalation = {"kind": "escalate", "reason": "lekkage"}
    for kind, payload in ((ActionType.request_contractor, request), (ActionType.escalate, escalation)):
        assert execute_action(env.deps, _approved(env, kind, payload, ButtonChoice.ok), 1).status == "sent"
    assert [m.payload["to"] for m in env.wa.sent] == [OWNER[1:], OWNER[1:]]
    assert "Copy and send" in env.wa.sent[0].payload["text"]["body"]
    assert env.replies.replies == []


def _plan(s: Session, env: Env, action_id: UUID) -> Plan:
    action = s.get(ActionRow, action_id)
    assert action is not None
    return plan_for(s, action, 1, f"exec:{action_id}:1", send_mode=True, now=datetime.now(UTC))


def test_mode_flipped_to_draft_after_planning_is_refused(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    with Session(env.engine) as s:
        plan = _plan(s, env, action_id)
        assert_allowed(s, env.company_id, plan)  # allowed while in send mode
        s.execute(update(Company).where(Company.id == env.company_id).values(outbound_mode=OutboundMode.draft))
        with pytest.raises(SendBlockedError, match="outbound mode is not send"):
            assert_allowed(s, env.company_id, plan)


def test_allowlist_rederives_the_recipient_and_ignores_the_plan(env: Env) -> None:
    action_id = _approved(env, ActionType.reply_draft, REPLY)
    with Session(env.engine) as s:
        plan = _plan(s, env, action_id)
        assert plan.draft is not None
        forged = replace(plan, target="other@example.test", draft=replace(plan.draft, to="other@example.test"))
        with pytest.raises(SendBlockedError, match="recipient is not the case contact"):
            assert_allowed(s, env.company_id, forged)


def test_tenant_target_without_the_tenant_flag_is_refused(env: Env) -> None:
    plan = Plan(Channel.whatsapp, TENANT_NR, whatsapp=payloads.text(TENANT_NR, "x"), case_id=env.case_id)
    with Session(env.engine) as s, pytest.raises(SendBlockedError, match="allowlist"):
        assert_allowed(s, env.company_id, plan)

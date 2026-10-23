"""Send mode (spec §5): an approved reply reaches the case contact, and only under every guard."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.channels.gmail.drafts import GmailDraftError
from app.channels.whatsapp import payloads
from app.contracts import ActionType, ButtonChoice, Channel, InteractiveChannel, OutboundMode
from app.db.enums import ActionStatus, FeedKind, PersonKind, SendStatus
from app.db.models import ActionRow, ChannelIdentity, Company, MessageRow, OwnerAccount, OwnerFeed, Person, Send
from app.sender.execute import execute_action
from app.sender.plan import Plan
from app.sender.targets import SendBlockedError, assert_allowed, owner_feed_target, plan_for
from app.sender.tenant_gate import GMAIL_SEND_MISSING
from tests.integration.send_mode_support import (
    OWNER,
    REPLY,
    TENANT_MAIL,
    TENANT_NR,
    VALID_FROM,
    Env,
    alert_row,
    approved,
    assert_blocked,
    make_env,
    send_count,
    set_company,
    set_rows,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


def test_draft_mode_still_creates_a_gmail_draft(env: Env) -> None:
    set_company(env, outbound_mode=OutboundMode.draft)
    action_id = approved(env, ActionType.reply_draft, {**REPLY, "subject": "Model subject"})
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [(r.body, r.subject) for r in env.drafts.created] == [("Optie B", "Re: Model subject")]  # unchanged
    assert env.replies.replies == []


def test_send_mode_subject_comes_from_the_thread_never_the_proposal(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, {**REPLY, "subject": "Model subject"})
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [r.subject for r in env.replies.replies] == ["Re: Lekkage badkamer"]


def test_send_mode_gmail_sends_one_reply_to_the_canonical_contact(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
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
    assert alert_row(env, action_id) is None


def test_send_mode_whatsapp_in_window_texts_the_contact(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, {**REPLY, "channel": "whatsapp"}, ButtonChoice.d1)
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert [(m.payload["to"], m.payload["text"]["body"]) for m in env.wa.sent] == [(TENANT_NR[1:], "Optie A")]


def test_whatsapp_window_closed_is_blocked_with_zero_calls(env: Env) -> None:
    old = datetime.now(UTC) - timedelta(hours=30)
    set_rows(env, MessageRow, sent_at=old, created_at=old)
    action_id = approved(env, ActionType.reply_draft, {**REPLY, "channel": "whatsapp"})
    assert_blocked(env, action_id, "WhatsApp window closed")
    assert send_count(env) == 0


def test_a_sender_that_is_no_longer_the_contacts_identity_is_blocked(env: Env) -> None:
    set_rows(env, ChannelIdentity, valid_to=datetime.now(UTC).date() - timedelta(days=1))
    assert_blocked(env, approved(env, ActionType.reply_draft, REPLY), "no inbound message from the case contact")


def test_paused_company_is_blocked_and_told(env: Env) -> None:
    set_company(env, paused=True)
    assert_blocked(env, approved(env, ActionType.reply_draft, REPLY), "company paused")


def test_reply_edited_after_approval_is_blocked(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
    with Session(env.engine) as s, s.begin():
        s.execute(update(ActionRow).where(ActionRow.id == action_id).values(draft_version=2))
    assert_blocked(env, action_id, "draft version superseded")


def test_missing_gmail_send_token_blocks_and_never_falls_back_to_a_draft(env: Env) -> None:
    env.deps = replace(env.deps, gmail_sender=None)
    assert_blocked(env, approved(env, ActionType.reply_draft, REPLY), GMAIL_SEND_MISSING)
    assert send_count(env) == 0


def test_ambiguous_gmail_failure_is_failed_not_retried_and_told(env: Env) -> None:
    calls: list[Any] = []

    def broken(request: Any) -> str:
        calls.append(request)
        raise GmailDraftError("sending reply failed: HTTP 503", retryable=False, maybe_sent=True)

    env.replies.send_reply = broken  # type: ignore[method-assign]
    action_id = approved(env, ActionType.reply_draft, REPLY)
    outcome = execute_action(env.deps, action_id, 1)
    assert outcome.status == "failed"
    assert "may have been delivered" in (outcome.reason or "")
    assert execute_action(env.deps, action_id, 1).status == "blocked"  # a failed action is never re-sent blindly
    assert len(calls) == 1
    alert = alert_row(env, action_id)
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
    set_rows(env, OwnerAccount, interactive_channel=InteractiveChannel.whatsapp)  # a WhatsApp owner: unchanged
    request = {"kind": "request_contractor", "contractor_person_id": _contractor(env), "body_variants": ["A", "B"]}
    escalation = {"kind": "escalate", "reason": "lekkage"}
    for kind, payload in ((ActionType.request_contractor, request), (ActionType.escalate, escalation)):
        assert execute_action(env.deps, approved(env, kind, payload, ButtonChoice.ok), 1).status == "sent"
    assert [m.payload["to"] for m in env.wa.sent] == [OWNER[1:], OWNER[1:]]
    assert "Copy and send" in env.wa.sent[0].payload["text"]["body"]
    assert env.replies.replies == []


def _feed_rows(env: Env) -> list[OwnerFeed]:
    with Session(env.engine) as s:
        return list(s.scalars(select(OwnerFeed).where(OwnerFeed.company_id == env.company_id)))


@pytest.mark.parametrize("mode", [OutboundMode.send, OutboundMode.draft])
def test_dashboard_owner_gets_an_approved_contractor_request_in_the_feed(env: Env, mode: OutboundMode) -> None:
    set_company(env, outbound_mode=mode)
    set_rows(env, OwnerAccount, interactive_channel=InteractiveChannel.dashboard)
    request = {"kind": "request_contractor", "contractor_person_id": _contractor(env), "body_variants": ["A", "B"]}
    action_id = approved(env, ActionType.request_contractor, request, ButtonChoice.ok)
    first = execute_action(env.deps, action_id, 1)
    assert (first.status, execute_action(env.deps, action_id, 1).status) == ("sent", "already")
    assert (env.wa.sent, env.replies.replies, env.drafts.created) == ([], [], [])
    [row] = _feed_rows(env)
    assert row.idempotency_key == feed.stored_key(env.company_id, f"exec:{action_id}:1")
    assert (row.kind, str(row.id)) == (FeedKind.alert, first.provider_ref)
    assert "Approved request for Jansen" in row.payload["text"]
    with Session(env.engine) as s:
        owner_id = s.scalar(select(OwnerAccount.id).where(OwnerAccount.company_id == env.company_id))
        send = s.scalar(select(Send).where(Send.action_id == action_id))
        assert send is not None
        assert owner_id is not None
        assert (send.channel, send.target, send.status) == (Channel.dashboard, owner_feed_target(owner_id),
                                                            SendStatus.sent)  # fmt: skip
        assert s.scalar(select(ActionRow.status).where(ActionRow.id == action_id)) is ActionStatus.executed


def test_dashboard_owner_gets_escalations_and_draft_mode_whatsapp_replies_in_the_feed(env: Env) -> None:
    set_company(env, outbound_mode=OutboundMode.draft)
    set_rows(env, OwnerAccount, interactive_channel=InteractiveChannel.dashboard)
    escalation = approved(env, ActionType.escalate, {"kind": "escalate", "reason": "lekkage"}, ButtonChoice.ok)
    reply = approved(env, ActionType.reply_draft, {**REPLY, "channel": "whatsapp"}, ButtonChoice.d1)
    assert [execute_action(env.deps, a, 1).status for a in (escalation, reply)] == ["sent", "sent"]
    assert env.wa.sent == []
    texts = sorted(r.payload["text"] for r in _feed_rows(env))
    assert texts[0].startswith("Approved reply for")
    assert texts[0].endswith("Optie A")
    assert texts[1] == "Escalation: lekkage"


def test_a_feed_plan_for_another_owner_is_refused(env: Env) -> None:
    set_rows(env, OwnerAccount, interactive_channel=InteractiveChannel.dashboard)
    action_id = approved(env, ActionType.escalate, {"kind": "escalate", "reason": "x"}, ButtonChoice.ok)
    with Session(env.engine) as s:
        plan = _plan(s, env, action_id)
        assert plan.channel is Channel.dashboard
        assert_allowed(s, env.company_id, plan)
        with pytest.raises(SendBlockedError, match="owner feed"):
            assert_allowed(s, env.company_id, replace(plan, target=owner_feed_target(env.case_id)))


def _plan(s: Session, env: Env, action_id: UUID) -> Plan:
    action = s.get(ActionRow, action_id)
    assert action is not None
    return plan_for(s, action, 1, f"exec:{action_id}:1", send_mode=True, now=datetime.now(UTC))


def test_mode_flipped_to_draft_after_planning_is_refused(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
    with Session(env.engine) as s:
        plan = _plan(s, env, action_id)
        assert_allowed(s, env.company_id, plan)  # allowed while in send mode
        s.execute(update(Company).where(Company.id == env.company_id).values(outbound_mode=OutboundMode.draft))
        with pytest.raises(SendBlockedError, match="outbound mode is not send"):
            assert_allowed(s, env.company_id, plan)


def test_allowlist_rederives_the_recipient_and_ignores_the_plan(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
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

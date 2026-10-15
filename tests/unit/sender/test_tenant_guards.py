"""Send-mode guards without a database: the allowlist decision, plan building, cap, routing and failure telling."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, Channel, Direction, DraftRequest, OutboundMode
from app.db.enums import FeedKind
from app.db.models import ActionRow, MessageRow
from app.sender.delivery import SenderDeps, deliver
from app.sender.errors import SendBlockedError
from app.sender.plan import Plan
from app.sender.targets import assert_allowed
from app.sender.tenant_gate import CAP_REACHED, GMAIL_SEND_MISSING, blocked_key, cap_reached, tell_owner, tenant_gate
from app.sender.tenant_plans import WINDOW_CLOSED, assert_tenant, tenant_gmail, tenant_refusal, tenant_whatsapp

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
TENANT_NR, TENANT_MAIL, MAILBOX, OWNER = "+31612345678", "sanne@example.test", "beheer@example.test", "+31600000100"
CASE, COMPANY = uuid4(), uuid4()
DRAFT = DraftRequest("exec:a:1", "thr-1", TENANT_MAIL, "Re: Lekkage", "Beste Sanne")
GMAIL = Plan(Channel.gmail, TENANT_MAIL, draft=DRAFT, mailbox=MAILBOX, tenant_send=True, case_id=CASE)
WA = Plan(Channel.whatsapp, TENANT_NR, whatsapp=payloads.text(TENANT_NR, "Hoi"), tenant_send=True, case_id=CASE)


# -- allowlist decision -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("plan", [GMAIL, WA])
def test_tenant_plan_in_send_mode_to_the_rederived_contact_passes(plan: Plan) -> None:
    assert tenant_refusal(plan, OutboundMode.send, plan.target) is None


@pytest.mark.parametrize("mode", [OutboundMode.draft, None])
def test_tenant_plan_outside_send_mode_is_refused(mode: OutboundMode | None) -> None:
    assert tenant_refusal(GMAIL, mode, TENANT_MAIL) == "outbound mode is not send: tenant replies are drafts only"


@pytest.mark.parametrize("expected", [None, "other@example.test", TENANT_MAIL.upper()])
def test_target_must_equal_the_rederived_recipient(expected: str | None) -> None:
    assert tenant_refusal(GMAIL, OutboundMode.send, expected) == "recipient is not the case contact"


def test_a_plan_without_the_tenant_flag_is_not_a_tenant_send() -> None:
    assert tenant_refusal(replace(WA, tenant_send=False), OutboundMode.send, TENANT_NR) == "not a tenant send"


@pytest.mark.parametrize(
    "plan",
    [
        replace(GMAIL, draft=replace(DRAFT, to="other@example.test")),  # header recipient differs from the target
        replace(GMAIL, mailbox=None),
        replace(GMAIL, draft=None),
        replace(GMAIL, whatsapp=payloads.text(TENANT_NR, "x")),
        replace(WA, whatsapp=payloads.text("+31699999999", "x")),  # payload recipient differs from the target
        replace(WA, draft=DRAFT),
        replace(WA, whatsapp=None),
    ],
)
def test_malformed_tenant_plans_are_refused(plan: Plan) -> None:
    reason = tenant_refusal(plan, OutboundMode.send, plan.target)
    assert reason is not None
    assert "malformed" in reason


def test_a_non_tenant_channel_is_refused() -> None:
    plan = Plan(Channel.google_chat, "spaces/x", google_chat={"text": "x"}, tenant_send=True, case_id=CASE)
    assert tenant_refusal(plan, OutboundMode.send, "spaces/x") == "google_chat is not a tenant reply channel"


def test_assert_tenant_rereads_the_mode_and_refuses_when_flipped_to_draft() -> None:
    session = MagicMock()
    session.scalar.return_value = OutboundMode.draft
    with (
        patch("app.sender.tenant_plans.tenant_recipient") as rederive,
        pytest.raises(SendBlockedError, match="outbound mode is not send"),
    ):
        assert_tenant(session, COMPANY, GMAIL)
    rederive.assert_not_called()


def test_assert_tenant_rederives_the_recipient_and_refuses_a_mismatch() -> None:
    session = MagicMock()
    session.scalar.return_value = OutboundMode.send
    with patch("app.sender.tenant_plans.tenant_recipient", return_value=(MagicMock(), "new@example.test")) as rederive:
        with pytest.raises(SendBlockedError, match="recipient is not the case contact"):
            assert_tenant(session, COMPANY, GMAIL)
        rederive.assert_called_once_with(session, COMPANY, CASE, Channel.gmail)
        rederive.return_value = (MagicMock(), TENANT_MAIL)
        assert_tenant(session, COMPANY, GMAIL)


def test_assert_allowed_refuses_a_tenant_number_without_the_tenant_flag() -> None:
    session = MagicMock()
    session.scalars.side_effect = [[], [OWNER]]  # owner emails, owner numbers
    with pytest.raises(SendBlockedError, match="allowlist"):
        assert_allowed(session, COMPANY, replace(WA, tenant_send=False))


def test_assert_allowed_routes_every_tenant_plan_through_assert_tenant() -> None:
    guard = MagicMock(side_effect=SendBlockedError("no"))
    with patch("app.sender.targets.assert_tenant", guard), pytest.raises(SendBlockedError):
        assert_allowed(MagicMock(), COMPANY, GMAIL)  # a Gmail plan with a draft no longer passes as "a draft"
    guard.assert_called_once()


# -- plan building -------------------------------------------------------------------------------------------------


def _msg(age: timedelta, sender: str = TENANT_NR, channel: Channel = Channel.whatsapp) -> MessageRow:
    return MessageRow(
        company_id=COMPANY, channel=channel, direction=Direction.inbound, sender_identity=sender, thread_ref="thr-1",
        sent_at=NOW - age, created_at=NOW - age, meta={"mailbox": MAILBOX, "subject": "Lekkage", "message_id": "<m1>"},
    )  # fmt: skip


def _action(channel: str) -> ActionRow:
    payload = {"kind": "reply_draft", "channel": channel, "subject": None, "body_variants": ["A"]}
    return ActionRow(company_id=COMPANY, case_id=CASE, type=ActionType.reply_draft, payload=payload)


def test_whatsapp_plan_goes_to_the_canonical_identity_inside_the_window() -> None:
    found = (_msg(timedelta(hours=22), sender="0031 6 12345678"), TENANT_NR)
    with patch("app.sender.tenant_plans.tenant_recipient", return_value=found):
        plan = tenant_whatsapp(MagicMock(), _action("whatsapp"), "x" * 5000, NOW)
    assert (plan.target, plan.tenant_send, plan.case_id, plan.channel) == (TENANT_NR, True, CASE, Channel.whatsapp)
    assert plan.whatsapp is not None
    assert plan.whatsapp["to"] == TENANT_NR.removeprefix("+")
    assert len(plan.whatsapp["text"]["body"]) == payloads.TEXT_BODY_MAX


def test_whatsapp_plan_is_blocked_when_the_window_closed() -> None:
    with (
        patch("app.sender.tenant_plans.tenant_recipient", return_value=(_msg(timedelta(hours=23)), TENANT_NR)),
        pytest.raises(SendBlockedError, match="WhatsApp window closed"),
    ):
        tenant_whatsapp(MagicMock(), _action("whatsapp"), "Hoi", NOW)
    assert WINDOW_CLOSED.startswith("WhatsApp window closed: the tenant wrote more than 23 h ago")


def test_gmail_plan_addresses_the_canonical_identity_not_the_raw_sender() -> None:
    session = MagicMock()
    session.scalar.return_value = MAILBOX  # the thread's mailbox is one of the company's accounts
    msg = _msg(timedelta(hours=2), sender="Sanne <Sanne@Example.TEST>", channel=Channel.gmail)
    with patch("app.sender.tenant_plans.tenant_recipient", return_value=(msg, TENANT_MAIL)):
        plan = tenant_gmail(session, _action("gmail"), "Beste Sanne", "exec:a:1")
    assert plan.draft is not None
    assert (plan.target, plan.draft.to, plan.tenant_send, plan.case_id) == (TENANT_MAIL, TENANT_MAIL, True, CASE)
    assert (plan.draft.thread_id, plan.draft.in_reply_to, plan.draft.body) == ("thr-1", "<m1>", "Beste Sanne")


# -- cap and gate --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("recent", "cap", "reached"), [(29, 30, False), (30, 30, True), (31, 30, True), (0, 0, True)])
def test_cap_is_reached_at_the_limit(recent: int, cap: int, reached: bool) -> None:
    assert cap_reached(recent, cap) is reached


def test_gate_ignores_owner_and_draft_plans_without_touching_the_db() -> None:
    session = MagicMock()
    assert (
        tenant_gate(session, COMPANY, "k", replace(GMAIL, tenant_send=False), NOW, cap=0, gmail_send_ready=False)
        is None
    )
    session.execute.assert_not_called()


def test_gate_blocks_gmail_sends_without_the_send_token() -> None:
    assert tenant_gate(MagicMock(), COMPANY, "k", GMAIL, NOW, cap=30, gmail_send_ready=False) == GMAIL_SEND_MISSING


def test_gate_blocks_at_the_cap() -> None:
    with patch("app.sender.tenant_gate.tenant_sends_last_hour", return_value=30) as count:
        assert tenant_gate(MagicMock(), COMPANY, "k", WA, NOW, cap=30, gmail_send_ready=False) == CAP_REACHED
        count.return_value = 29
        assert tenant_gate(MagicMock(), COMPANY, "k", WA, NOW, cap=30, gmail_send_ready=False) is None


# -- delivery routing ----------------------------------------------------------------------------------------------


def _deps(sender: Any) -> tuple[SenderDeps, MagicMock, FakeWhatsAppOutbound]:
    drafts, wa = MagicMock(), FakeWhatsAppOutbound()
    return SenderDeps(MagicMock(), wa, lambda _a: drafts, gmail_sender=sender), drafts, wa


def test_tenant_gmail_is_sent_with_the_send_adapter_never_as_a_draft() -> None:
    sender = MagicMock()
    sender.send_reply.return_value = "msg-1"
    deps, drafts, _ = _deps(lambda _a: sender)
    assert deliver(deps, GMAIL) == "msg-1"
    sender.send_reply.assert_called_once_with(DRAFT)
    drafts.create_draft.assert_not_called()


def test_tenant_gmail_without_a_send_adapter_is_blocked() -> None:
    deps, drafts, _ = _deps(None)
    with pytest.raises(SendBlockedError, match="not configured"):
        deliver(deps, GMAIL)
    drafts.create_draft.assert_not_called()


def test_draft_plans_still_create_drafts_and_tenant_whatsapp_uses_whatsapp() -> None:
    deps, drafts, wa = _deps(None)
    deliver(deps, replace(GMAIL, tenant_send=False))
    drafts.create_draft.assert_called_once_with(DRAFT)
    deliver(deps, WA)
    assert [m.payload["to"] for m in wa.sent] == [TENANT_NR.removeprefix("+")]


# -- failure telling -----------------------------------------------------------------------------------------------


def test_tell_owner_writes_one_alert_with_the_reason_and_no_body() -> None:
    action_id = uuid4()
    with patch("app.sender.tenant_gate.Session"), patch("app.sender.tenant_gate.feed.deliver") as feed_deliver:
        tell_owner(MagicMock(), COMPANY, action_id, 2, WINDOW_CLOSED)
    args = feed_deliver.call_args.args
    assert args[1:5] == (COMPANY, f"blocked:{action_id}:2", FeedKind.alert, None)
    assert WINDOW_CLOSED in args[5].text
    assert blocked_key(action_id, 2) == f"blocked:{action_id}:2"


def test_tell_owner_never_raises() -> None:
    with patch("app.sender.tenant_gate.Session", side_effect=RuntimeError("db down")):
        tell_owner(MagicMock(), COMPANY, uuid4(), 1, "x")

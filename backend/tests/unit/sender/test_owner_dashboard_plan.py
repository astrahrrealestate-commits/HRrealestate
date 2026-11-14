"""Approved owner-directed actions follow the owner's channel: the dashboard feed for a dashboard owner (no DB)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import ActionType, Channel, InteractiveChannel, OwnerMessage
from app.db.enums import FeedKind, SendStatus
from app.sender.delivery import ExecOutcome, SenderDeps, send_claimed
from app.sender.plan import Plan
from app.sender.targets import SendBlockedError, assert_allowed, owner_feed_target, plan_for

COMPANY, OWNER_ID, CONTRACTOR = uuid4(), uuid4(), uuid4()
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
KEY = "exec:a:1"


def _owner(channel: InteractiveChannel) -> SimpleNamespace:
    return SimpleNamespace(id=OWNER_ID, interactive_channel=channel, whatsapp_e164="+31600000100")


def _action(kind: ActionType, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), company_id=COMPANY, case_id=uuid4(), type=kind, payload=payload)


def _plan(kind: ActionType, payload: dict[str, Any], scalars: list[Any]) -> Plan:
    session = MagicMock()
    session.scalar.side_effect = scalars
    session.scalars.return_value.all.return_value = ["+31688888888"]
    return plan_for(session, _action(kind, payload), 0, KEY, send_mode=False, now=NOW)  # type: ignore[arg-type]


REQUEST = {"contractor_person_id": str(CONTRACTOR), "body_variants": ["Kunt u morgen komen?"]}


@pytest.mark.parametrize(
    ("kind", "payload", "scalars", "text"),
    [
        (ActionType.request_contractor, REQUEST, ["Jansen"], "Approved request for Jansen (+31688888888)"),
        (ActionType.escalate, {"reason": "lekkage"}, [], "Escalation: lekkage"),
        (ActionType.notify_owner, {"text": "Huur ontvangen"}, [], "Huur ontvangen"),
    ],
)
def test_dashboard_owner_gets_a_feed_plan(
    kind: ActionType, payload: dict[str, Any], scalars: list[Any], text: str
) -> None:
    plan = _plan(kind, payload, [*scalars, _owner(InteractiveChannel.dashboard)])
    assert (plan.channel, plan.target, plan.company_id) == (Channel.dashboard, owner_feed_target(OWNER_ID), COMPANY)
    assert plan.owner_message is not None
    assert plan.owner_message.text.startswith(text)
    assert (plan.whatsapp, plan.draft, plan.email, plan.tenant_send) == (None, None, None, False)


def test_draft_mode_whatsapp_reply_goes_to_a_dashboard_owners_feed() -> None:
    reply = {"channel": "whatsapp", "body_variants": ["Dag Sanne"]}
    with patch("app.sender.targets.latest_inbound", return_value=None):
        plan = _plan(ActionType.reply_draft, reply, [_owner(InteractiveChannel.dashboard)])
    assert plan.channel is Channel.dashboard
    assert plan.owner_message is not None
    assert plan.owner_message.text.endswith("Dag Sanne")


@pytest.mark.parametrize("channel", [InteractiveChannel.whatsapp, InteractiveChannel.google_chat])
def test_whatsapp_and_chat_owners_keep_the_whatsapp_text(channel: InteractiveChannel) -> None:
    plan = _plan(ActionType.escalate, {"reason": "lekkage"}, [_owner(channel), "+31600000100"])
    assert (plan.channel, plan.target, plan.owner_message) == (Channel.whatsapp, "+31600000100", None)
    assert plan.whatsapp is not None
    assert plan.whatsapp["text"]["body"] == "Escalation: lekkage"


def _feed_plan(**changes: Any) -> Plan:
    values: dict[str, Any] = {
        "channel": Channel.dashboard,
        "target": owner_feed_target(OWNER_ID),
        "owner_message": OwnerMessage(text="x"),
        "company_id": COMPANY,
        **changes,
    }
    return Plan(**values)


def _allowed(plan: Plan, owners: list[UUID]) -> None:
    session = MagicMock()
    session.scalars.return_value = owners
    assert_allowed(session, COMPANY, plan)


def test_a_feed_plan_for_the_companys_own_dashboard_owner_is_allowed() -> None:
    _allowed(_feed_plan(), [OWNER_ID])


@pytest.mark.parametrize(
    "plan",
    [
        _feed_plan(company_id=uuid4()),  # another company's feed
        _feed_plan(target=owner_feed_target(uuid4())),  # not this company's dashboard owner
        _feed_plan(owner_message=None),
        _feed_plan(whatsapp={"to": "31600000100"}),  # a provider payload smuggled into a feed plan
    ],
)
def test_any_other_feed_plan_is_refused(plan: Plan) -> None:
    with pytest.raises(SendBlockedError, match="owner feed"):
        _allowed(plan, [OWNER_ID])


def test_no_dashboard_owner_means_no_feed_delivery() -> None:
    with pytest.raises(SendBlockedError, match="owner feed"):
        _allowed(_feed_plan(), [])


def _feed_send(status: SendStatus) -> SimpleNamespace:
    return SimpleNamespace(status=status, provider_ref="old", action_id=uuid4(), error=None, attempted_at=None)


def test_a_claimed_feed_plan_writes_the_feed_under_the_exec_key_and_calls_no_provider() -> None:
    wa, row_id, send = FakeWhatsAppOutbound(), uuid4(), _feed_send(SendStatus.pending)
    deps = SenderDeps(MagicMock(), wa, lambda _a: MagicMock())
    plan = _feed_plan()
    with (
        patch("app.sender.delivery.Session") as session_cls,
        patch("app.sender.delivery.feed.deliver", return_value=row_id) as deliver,
        patch("app.sender.delivery.begin_attempt") as begin,
    ):
        session_cls.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = send
        outcome = send_claimed(deps, KEY, plan)
    assert outcome == ExecOutcome("sent", provider_ref=str(row_id))
    assert deliver.call_args.args[1:] == (COMPANY, KEY, FeedKind.alert, None, plan.owner_message)
    assert (send.status, send.provider_ref) == (SendStatus.sent, str(row_id))
    begin.assert_not_called()  # feed row and sent mark commit together: no separate attempt to lose
    assert wa.sent == []


def test_a_replayed_feed_plan_is_already_and_writes_nothing() -> None:
    deps = SenderDeps(MagicMock(), FakeWhatsAppOutbound(), lambda _a: MagicMock())
    with (
        patch("app.sender.delivery.Session") as session_cls,
        patch("app.sender.delivery.feed.deliver") as deliver,
    ):
        session_cls.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = _feed_send(
            SendStatus.sent
        )
        assert send_claimed(deps, KEY, _feed_plan()) == ExecOutcome("already", provider_ref="old")
    deliver.assert_not_called()

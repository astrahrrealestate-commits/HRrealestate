"""Send mode: replays, stuck sends, the hourly cap and channel/body limits."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine

from app.channels.gmail.drafts import GmailDraftError
from app.contracts import ActionType, ButtonChoice, Channel, OutboundMode
from app.db.enums import SendStatus
from app.db.models import Company, MessageRow
from app.sender.delivery import REUSED_KEY, STATUS_UNKNOWN
from app.sender.execute import execute_action
from app.sender.tenant_gate import CAP_REACHED
from app.sender.tenant_plans import TOO_LONG, UNSUPPORTED_CHANNEL
from tests.integration.send_mode_support import (
    OWNER,
    REPLY,
    TENANT_MAIL,
    Env,
    alert_row,
    approved,
    assert_blocked,
    make_env,
    prior_send,
    send_count,
    set_company,
    set_rows,
)

pytestmark = pytest.mark.integration
WHATSAPP = {**REPLY, "channel": "whatsapp"}


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


def test_hourly_cap_blocks_tenant_sends(env: Env) -> None:
    env.deps = replace(env.deps, tenant_sends_per_hour=1)
    prior_send(env, "+31699999999")
    assert_blocked(env, approved(env, ActionType.reply_draft, REPLY), CAP_REACHED)


@pytest.mark.parametrize(("target", "status"), [(OWNER, SendStatus.sent), ("+31699999999", SendStatus.failed)])
def test_owner_messages_and_failed_rows_do_not_count_against_the_cap(env: Env, target: str, status: SendStatus) -> None:
    env.deps = replace(env.deps, tenant_sends_per_hour=1)
    prior_send(env, target, status=status)
    assert execute_action(env.deps, approved(env, ActionType.reply_draft, REPLY), 1).status == "sent"


def test_a_retry_at_the_cap_is_not_blocked_by_its_own_row(env: Env) -> None:
    env.deps = replace(env.deps, tenant_sends_per_hour=1)
    original, failed = env.replies.send_reply, list[int]()

    def flaky(request: Any) -> str:
        if not failed:
            failed.append(1)
            raise GmailDraftError("sending reply rate-limited: HTTP 429", retryable=True)
        return original(request)

    env.replies.send_reply = flaky  # type: ignore[method-assign]
    action_id = approved(env, ActionType.reply_draft, REPLY)
    with pytest.raises(GmailDraftError):
        execute_action(env.deps, action_id, 1)  # leaves this key's row pending: it must not count against itself
    assert execute_action(env.deps, action_id, 1).status == "sent"
    assert len(env.replies.replies) == 1


def test_a_stuck_sending_row_is_reported_unknown_never_done(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
    prior_send(env, TENANT_MAIL, status=SendStatus.sending, channel=Channel.gmail, key=f"exec:{action_id}:1",
               action_id=action_id)  # fmt: skip
    outcome = execute_action(env.deps, action_id, 1)
    assert (outcome.status, outcome.reason) == ("failed", STATUS_UNKNOWN)
    assert env.replies.replies == []
    alert = alert_row(env, action_id)
    assert alert is not None
    assert "delivery status unknown" in alert.payload["text"]


def test_replay_after_a_real_send_is_already_even_when_the_checks_now_fail(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, WHATSAPP)
    assert execute_action(env.deps, action_id, 1).status == "sent"
    old = datetime.now(UTC) - timedelta(hours=30)
    set_rows(env, MessageRow, sent_at=old, created_at=old)  # window closed since
    set_company(env, paused=True)
    assert execute_action(env.deps, action_id, 1).status == "already"
    assert alert_row(env, action_id) is None  # no false "not sent"
    assert len(env.wa.sent) == 1


def test_draft_mode_blocked_writes_no_alert(env: Env) -> None:
    set_company(env, outbound_mode=OutboundMode.draft, paused=True)
    action_id = approved(env, ActionType.reply_draft, REPLY)
    assert execute_action(env.deps, action_id, 1).status == "blocked"
    assert alert_row(env, action_id) is None


def test_an_existing_row_for_another_recipient_blocks_the_claim(env: Env) -> None:
    action_id = approved(env, ActionType.reply_draft, REPLY)
    prior_send(env, "other@example.test", status=SendStatus.pending, channel=Channel.gmail,
               key=f"exec:{action_id}:1", action_id=action_id)  # fmt: skip
    assert_blocked(env, action_id, REUSED_KEY)


@pytest.mark.parametrize("channel", ["google_chat", "dashboard", None])
def test_only_gmail_and_whatsapp_reply_channels_are_sent(env: Env, channel: str | None) -> None:
    assert_blocked(env, approved(env, ActionType.reply_draft, {**REPLY, "channel": channel}), UNSUPPORTED_CHANNEL)
    assert send_count(env) == 0


def test_an_overlong_whatsapp_reply_is_blocked_not_trimmed(env: Env) -> None:
    payload = {**WHATSAPP, "body_variants": ["x" * 5000]}
    assert_blocked(env, approved(env, ActionType.reply_draft, payload, ButtonChoice.d1), TOO_LONG)

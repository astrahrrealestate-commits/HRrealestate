"""Pure send-mode rules: thread subject, reply channel, body limits, lost attempts, `sends` row reuse."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.channels.whatsapp import payloads
from app.contracts import Channel
from app.db.enums import SendStatus
from app.db.models import Send
from app.sender.delivery import (
    IN_PROGRESS,
    REUSED_KEY,
    STATUS_UNKNOWN,
    STUCK,
    ExecOutcome,
    lost_attempt,
    reuse_refusal,
    stuck,
)
from app.sender.errors import SendBlockedError
from app.sender.gmail_reply import thread_subject
from app.sender.plan import Plan
from app.sender.tenant_plans import EMPTY_BODY, TOO_LONG, UNSUPPORTED_CHANNEL, body_refusal, reply_channel

COMPANY = uuid4()


@pytest.mark.parametrize(
    ("stored", "subject"),
    [
        ("Lekkage badkamer", "Re: Lekkage badkamer"),
        ("Re: Lekkage", "Re: Lekkage"),
        ("RE: re:Re :  Lekkage", "Re: Lekkage"),
        ("  ", "Re:"),
        ("Re:", "Re:"),
        (None, "Re:"),
        ("Reparatie", "Re: Reparatie"),  # a word starting with "Re" is not a prefix
    ],
)
def test_thread_subject(stored: str | None, subject: str) -> None:
    assert thread_subject(stored) == subject


@pytest.mark.parametrize(("value", "channel"), [("gmail", Channel.gmail), ("whatsapp", Channel.whatsapp)])
def test_reply_channel_names_gmail_or_whatsapp(value: str, channel: Channel) -> None:
    assert reply_channel(value) is channel


@pytest.mark.parametrize("value", ["google_chat", "dashboard", None, "", "Gmail", 1])
def test_any_other_reply_channel_is_unsupported(value: object) -> None:
    with pytest.raises(SendBlockedError, match=UNSUPPORTED_CHANNEL):
        reply_channel(value)


def test_body_limits() -> None:
    assert body_refusal("x" * payloads.TEXT_BODY_MAX, Channel.whatsapp) is None
    assert body_refusal("x" * (payloads.TEXT_BODY_MAX + 1), Channel.whatsapp) == TOO_LONG
    assert body_refusal("x" * (payloads.TEXT_BODY_MAX + 1), Channel.gmail) is None
    assert body_refusal(" \n", Channel.gmail) == EMPTY_BODY
    assert body_refusal("", Channel.whatsapp) == EMPTY_BODY


@pytest.mark.parametrize("tenant", [True, False])
def test_a_lost_attempt_on_a_sent_row_is_already(tenant: bool) -> None:
    assert lost_attempt(tenant, SendStatus.sent, "ref-1") == ExecOutcome("already", provider_ref="ref-1")


NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("status", [SendStatus.failed, SendStatus.pending, None])
def test_a_lost_tenant_attempt_on_a_failed_row_stays_failed_unknown(status: SendStatus | None) -> None:
    assert lost_attempt(True, status, None, NOW - timedelta(hours=2), NOW) == ExecOutcome(
        "failed", reason=STATUS_UNKNOWN
    )


AGES = [timedelta(seconds=5), timedelta(minutes=9), timedelta(minutes=15), timedelta(minutes=29)]


@pytest.mark.parametrize("age", AGES)
def test_a_recent_sending_row_is_in_progress_without_failure_or_alert(age: timedelta) -> None:
    outcome = lost_attempt(True, SendStatus.sending, None, NOW - age, NOW)
    assert outcome == ExecOutcome("in_progress", reason=IN_PROGRESS)  # not "already": nothing was sent yet


@pytest.mark.parametrize("attempted", [NOW - timedelta(minutes=30), NOW - timedelta(hours=5), None])
def test_a_sending_row_older_than_30_minutes_is_stuck(attempted: datetime | None) -> None:
    assert lost_attempt(True, SendStatus.sending, None, attempted, NOW) == ExecOutcome("failed", reason=STUCK)
    assert stuck(attempted, NOW)
    assert "check the thread" in STUCK


def test_stuck_boundary() -> None:
    assert not stuck(NOW - timedelta(minutes=29, seconds=59), NOW)
    assert stuck(NOW - timedelta(minutes=30), NOW)


@pytest.mark.parametrize("status", [SendStatus.sending, SendStatus.failed, SendStatus.pending, None])
def test_owner_directed_lost_attempts_are_in_progress_unless_sent(status: SendStatus | None) -> None:
    """Only a sent row is "already"; the holder of an owner-directed send reports its own outcome."""
    assert lost_attempt(False, status, None).status == "in_progress"


def _row(channel: Channel = Channel.gmail, target: str = "sanne@example.test") -> Send:
    return Send(company_id=COMPANY, idempotency_key="exec:a:1", channel=channel, target=target)


PLAN = Plan(Channel.gmail, "sanne@example.test", tenant_send=True)


def test_a_row_is_reused_only_for_the_same_company_channel_and_recipient() -> None:
    assert reuse_refusal(_row(), COMPANY, PLAN) is None
    assert reuse_refusal(_row(target="other@example.test"), COMPANY, PLAN) == REUSED_KEY
    assert reuse_refusal(_row(channel=Channel.whatsapp), COMPANY, PLAN) == REUSED_KEY
    assert reuse_refusal(_row(), uuid4(), PLAN) == REUSED_KEY

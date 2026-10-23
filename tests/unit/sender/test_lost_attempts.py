"""send_claimed after losing the claim (no DB): in-flight tenant sends report nothing, stuck ones fail once."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import Channel
from app.db.enums import SendStatus
from app.sender.delivery import IN_PROGRESS, STATUS_UNKNOWN, STUCK, ExecOutcome, SenderDeps, send_claimed
from app.sender.plan import Plan
from app.sender.tenant_gate import alert_text

TENANT = Plan(Channel.gmail, "sanne@example.test", tenant_send=True)
D = "app.sender.delivery"


def _run(rows: list[tuple[SendStatus, None, datetime | None]], won: bool) -> tuple[ExecOutcome, MagicMock]:
    deps = SenderDeps(MagicMock(), FakeWhatsAppOutbound(), lambda _a: MagicMock())
    with (
        patch(f"{D}.begin_attempt", return_value=False),
        patch(f"{D}._current", side_effect=rows),
        patch(f"{D}.give_up_stuck", return_value=won) as give_up,
    ):
        return send_claimed(deps, "exec:a:1", TENANT), give_up


def _ago(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


def test_in_flight_send_is_in_progress_and_never_given_up() -> None:
    for minutes in (1, 12, 25):
        outcome, give_up = _run([(SendStatus.sending, None, _ago(minutes))], won=True)
        assert outcome == ExecOutcome("already", reason=IN_PROGRESS)
        give_up.assert_not_called()


def test_stuck_send_is_marked_failed_by_the_caller_that_wins() -> None:
    outcome, give_up = _run([(SendStatus.sending, None, _ago(45))], won=True)
    assert outcome == ExecOutcome("failed", reason=STUCK)
    give_up.assert_called_once()


def test_a_caller_that_loses_the_give_up_rereads_the_row() -> None:
    outcome, _ = _run([(SendStatus.sending, None, _ago(45)), (SendStatus.failed, None, _ago(45))], won=False)
    assert outcome == ExecOutcome("failed", reason=STATUS_UNKNOWN)


def test_the_alert_never_claims_not_sent_when_the_tenant_may_have_it() -> None:
    assert alert_text(STUCK) == f"Reply may not have reached the tenant: {STUCK}."
    assert alert_text("may have been delivered: X").startswith("Reply may not have reached the tenant")
    assert alert_text("company paused") == "Reply not sent to the tenant: company paused."

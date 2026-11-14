"""`execute_action_wf` body (no DBOS runtime): exhausted send retries are told and end the workflow in ERROR."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.contracts import ActionType
from app.sender.delivery import STUCK
from app.sender.tenant_gate import alert_text, blocked_key, blocked_text
from app.workflows import actions

WF: Callable[[str, int, bool], str] = inspect.unwrap(actions.execute_action_wf)  # undecorated body


class _ExhaustedError(Exception):
    pass


def _run(
    send: MagicMock, workflow_id: str = "exec:a:1", snapshot: MagicMock | None = None
) -> tuple[MagicMock, MagicMock]:
    tell, after = MagicMock(), MagicMock()
    with (
        patch.object(actions, "send_step", send),
        patch.object(actions, "tell_blocked_step", tell),
        patch.object(actions, "after_execute_step", after),
        patch.object(actions, "snapshot_after_approval", snapshot or MagicMock()),
        patch.object(actions, "DBOS", MagicMock(workflow_id=workflow_id)),
    ):
        WF("a", 1, False)
    return tell, after


def test_exhausted_send_retries_tell_the_owner_and_reraise() -> None:
    tell, after, snapshot = MagicMock(), MagicMock(), MagicMock()
    with (
        patch.object(actions, "send_step", MagicMock(side_effect=_ExhaustedError("429 x6"))),
        patch.object(actions, "tell_blocked_step", tell),
        patch.object(actions, "after_execute_step", after),
        patch.object(actions, "snapshot_after_approval", snapshot),
        patch.object(actions, "DBOS", MagicMock(workflow_id="exec:a:1")),
        pytest.raises(_ExhaustedError),
    ):
        WF("a", 1, False)
    tell.assert_called_once_with("a", 1, actions.EXHAUSTED)
    after.assert_not_called()
    snapshot.assert_called_once_with("a")  # the approval, not the delivery, triggers the snapshot (R24)
    assert "429" not in actions.EXHAUSTED  # no provider/exception text reaches the owner


@pytest.mark.parametrize(("outcome", "told", "after_called"), [
    ("sent", False, True), ("already", False, True), ("blocked", True, False), ("failed", True, False),
    ("in_progress", False, False),  # another attempt holds the send: it (or the stuck sweep) settles it
])  # fmt: skip
def test_returned_outcomes_are_handled_as_before(outcome: str, told: bool, after_called: bool) -> None:
    tell, after = _run(MagicMock(return_value=[outcome, "why"]))
    assert tell.called is told
    assert after.called is after_called
    if told:
        tell.assert_called_once_with("a", 1, "why")


@pytest.mark.parametrize("outcome", ["sent", "already", "blocked", "failed", "in_progress"])
def test_every_execution_outcome_runs_the_snapshot_hook_once(outcome: str) -> None:
    snapshot = MagicMock()
    _run(MagicMock(return_value=[outcome, "why"]), snapshot=snapshot)
    snapshot.assert_called_once_with("a")


def test_a_local_execution_runs_the_snapshot_hook_too() -> None:
    snapshot = MagicMock()
    with (
        patch.object(actions, "apply_local_step", MagicMock(return_value="applied")),
        patch.object(actions, "snapshot_after_approval", snapshot),
    ):
        WF("a", 1, True)
    snapshot.assert_called_once_with("a")


def test_a_resume_run_tells_under_the_action_version_not_its_workflow_id() -> None:
    tell, _ = _run(MagicMock(return_value=["failed", "why"]), workflow_id="exec:a:1:resume:r1")
    tell.assert_called_once_with("a", 1, "why")


def _tell(kind: ActionType, reason: str) -> tuple[MagicMock, UUID, UUID]:
    action_id, company_id = uuid4(), uuid4()
    step = inspect.unwrap(actions.tell_blocked_step)
    with (
        patch.object(actions, "Session") as session,
        patch.object(actions, "get_engine"),
        patch.object(actions, "send_owner_message") as send,
    ):
        session.return_value.__enter__.return_value.execute.return_value.first.return_value = (company_id, kind)
        step(str(action_id), 3, reason)
    return send, action_id, company_id


def _told_text(send: MagicMock) -> str:
    return str(send.call_args.args[2]("+31600000100")["text"]["body"])


def test_tell_blocked_uses_the_senders_alert_key() -> None:
    send, action_id, company_id = _tell(ActionType.notify_owner, "company paused")
    assert send.call_args.args[:2] == (str(company_id), blocked_key(action_id, 3))


def test_a_tenant_reply_alert_never_says_not_sent_when_it_may_have_arrived() -> None:
    send, _, _ = _tell(ActionType.reply_draft, STUCK)
    assert _told_text(send) == alert_text(STUCK)
    assert "Not sent" not in _told_text(send)


def test_a_paused_tenant_reply_alert_names_resume() -> None:
    send, _, _ = _tell(ActionType.reply_draft, "company paused")
    assert _told_text(send) == "Reply not sent to the tenant: company paused. Send `resume` to run approved actions."


def test_owner_directed_alerts_keep_their_wording() -> None:
    send, _, _ = _tell(ActionType.request_contractor, "approval no longer valid")
    assert _told_text(send) == "Not sent: approval no longer valid."


@pytest.mark.parametrize(
    ("reason", "tenant", "text"),
    [
        ("company paused", False, "Not sent: company paused. Send `resume` to run approved actions."),
        ("", False, "Not sent: the approval is no longer valid."),
        (STUCK, True, f"Reply may not have reached the tenant: {STUCK}."),
        ("hourly tenant send cap reached", True, "Reply not sent to the tenant: hourly tenant send cap reached."),
    ],
)
def test_blocked_text(reason: str, tenant: bool, text: str) -> None:
    assert blocked_text(reason, tenant) == text

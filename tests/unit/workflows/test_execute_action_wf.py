"""`execute_action_wf` body (no DBOS runtime): exhausted send retries are told and end the workflow in ERROR."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.sender.tenant_gate import blocked_key
from app.workflows import actions

WF: Callable[[str, int, bool], str] = inspect.unwrap(actions.execute_action_wf)  # undecorated body


class _ExhaustedError(Exception):
    pass


def _run(send: MagicMock, workflow_id: str = "exec:a:1") -> tuple[MagicMock, MagicMock]:
    tell, after = MagicMock(), MagicMock()
    with (
        patch.object(actions, "send_step", send),
        patch.object(actions, "tell_blocked_step", tell),
        patch.object(actions, "after_execute_step", after),
        patch.object(actions, "DBOS", MagicMock(workflow_id=workflow_id)),
    ):
        WF("a", 1, False)
    return tell, after


def test_exhausted_send_retries_tell_the_owner_and_reraise() -> None:
    tell, after = MagicMock(), MagicMock()
    with (
        patch.object(actions, "send_step", MagicMock(side_effect=_ExhaustedError("429 x6"))),
        patch.object(actions, "tell_blocked_step", tell),
        patch.object(actions, "after_execute_step", after),
        patch.object(actions, "DBOS", MagicMock(workflow_id="exec:a:1")),
        pytest.raises(_ExhaustedError),
    ):
        WF("a", 1, False)
    tell.assert_called_once_with("a", 1, actions.EXHAUSTED)
    after.assert_not_called()
    assert "429" not in actions.EXHAUSTED  # no provider/exception text reaches the owner


@pytest.mark.parametrize(("outcome", "told", "after_called"), [
    ("sent", False, True), ("already", False, True), ("blocked", True, False), ("failed", True, False),
])  # fmt: skip
def test_returned_outcomes_are_handled_as_before(outcome: str, told: bool, after_called: bool) -> None:
    tell, after = _run(MagicMock(return_value=[outcome, "why"]))
    assert tell.called is told
    assert after.called is after_called
    if told:
        tell.assert_called_once_with("a", 1, "why")


def test_a_resume_run_tells_under_the_action_version_not_its_workflow_id() -> None:
    tell, _ = _run(MagicMock(return_value=["failed", "why"]), workflow_id="exec:a:1:resume:r1")
    tell.assert_called_once_with("a", 1, "why")


def test_tell_blocked_uses_the_senders_alert_key() -> None:
    action_id, company_id = uuid4(), uuid4()
    step = inspect.unwrap(actions.tell_blocked_step)
    with (
        patch.object(actions, "Session") as session,
        patch.object(actions, "get_engine"),
        patch.object(actions, "send_owner_message") as send,
    ):
        session.return_value.__enter__.return_value.scalar.return_value = company_id
        step(str(action_id), 3, "company paused")
    assert send.call_args.args[:2] == (str(company_id), blocked_key(action_id, 3))

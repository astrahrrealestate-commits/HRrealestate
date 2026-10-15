"""`execute_action_wf` body (no DBOS runtime): exhausted send retries are told and end the workflow in ERROR."""

import inspect
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from app.workflows import actions

WF: Callable[[str, int, bool], str] = inspect.unwrap(actions.execute_action_wf)  # undecorated body


class _ExhaustedError(Exception):
    pass


def _run(send: MagicMock) -> tuple[MagicMock, MagicMock]:
    tell, after = MagicMock(), MagicMock()
    with (
        patch.object(actions, "send_step", send),
        patch.object(actions, "tell_blocked_step", tell),
        patch.object(actions, "after_execute_step", after),
        patch.object(actions, "DBOS", MagicMock(workflow_id="exec:a:1")),
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
    tell.assert_called_once_with("a", "exec:a:1", actions.EXHAUSTED)
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
        tell.assert_called_once_with("a", "exec:a:1", "why")

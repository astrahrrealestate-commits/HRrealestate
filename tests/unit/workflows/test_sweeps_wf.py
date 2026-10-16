"""`sweep.stranded` body and its candidates step (no DBOS runtime): same ids as the API, known ids skipped."""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import ActionType
from app.pipeline import sweeps as pipeline_sweeps
from app.sender import stuck
from app.sender.delivery import STUCK
from app.sender.stuck import StuckSend
from app.workflows import sweeps as wf
from app.workflows.runtime import SCHEDULES

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
A, T = uuid4(), uuid4()
BODY: Callable[[datetime, Any], None] = inspect.unwrap(wf.sweep_stranded)
STEP: Callable[[str], list[dict[str, Any]]] = inspect.unwrap(wf.candidates_step)


def test_the_sweep_runs_every_five_minutes() -> None:
    [entry] = [s for s in SCHEDULES if s["schedule_name"] == "sweep.stranded"]
    assert (entry["workflow_fn"], entry["schedule"]) == (wf.sweep_stranded, "*/5 * * * *")


def test_candidates_skip_workflow_ids_dbos_already_has() -> None:
    known = [SimpleNamespace(workflow_id=f"concierge:{T}")]
    with (
        patch.object(wf, "get_engine"),
        patch.object(wf.sweeps, "stranded", return_value=([(A, 3, ActionType.notify_owner)], [T])) as stranded,
        patch.object(wf, "DBOS") as dbos,
    ):
        dbos.list_workflows.return_value = known
        items = STEP(NOW.isoformat())
    assert stranded.call_args.args[1] == NOW
    assert dbos.list_workflows.call_args.kwargs["workflow_ids"] == [f"exec:{A}:3", f"concierge:{T}"]
    assert items == [{"kind": "exec", "workflow_id": f"exec:{A}:3", "args": (str(A), 3, False)}]


def test_nothing_stranded_asks_dbos_nothing() -> None:
    with (
        patch.object(wf, "get_engine"),
        patch.object(wf.sweeps, "stranded", return_value=([], [])),
        patch.object(wf, "DBOS") as dbos,
    ):
        assert STEP(NOW.isoformat()) == []
    dbos.list_workflows.assert_not_called()


def test_each_item_is_enqueued_under_its_own_deterministic_id() -> None:
    items = [
        {"kind": "exec", "workflow_id": f"exec:{A}:3", "args": (str(A), 3, False)},
        {"kind": "turn", "workflow_id": f"concierge:{T}", "args": (str(T),)},
    ]
    ids: list[str] = []
    queue = MagicMock()
    with (
        patch.object(wf, "candidates_step", return_value=items) as step,
        patch.object(wf, "stuck_sends_step", return_value=[]),
        patch.object(wf.queues, "pipeline_queue", return_value=queue),
        patch.object(wf, "SetWorkflowID", side_effect=lambda wid: ids.append(wid) or MagicMock()),
    ):
        BODY(NOW, None)
    assert step.call_args.args == (NOW.isoformat(),)
    assert ids == [f"exec:{A}:3", f"concierge:{T}"]
    assert [c.args for c in queue.enqueue.call_args_list] == [
        (wf.execute_action_wf, str(A), 3, False),
        (wf.concierge_turn, str(T)),
    ]


def test_known_actions_cannot_starve_newer_stranded_ones() -> None:
    """Blocked actions keep `approved` with no send row but have a finished run: they must not fill the batch."""
    blocked = [(uuid4(), 1, ActionType.reply_draft) for _ in range(250)]
    fresh = [(uuid4(), 1, ActionType.reply_draft) for _ in range(10)]
    known = [SimpleNamespace(workflow_id=f"exec:{a}:1") for a, _, _ in blocked]
    with (
        patch.object(wf, "get_engine"),
        patch.object(pipeline_sweeps, "stranded", return_value=(blocked + fresh, [])) as stranded,
        patch.object(wf, "DBOS") as dbos,
    ):
        dbos.list_workflows.return_value = known
        items = STEP(NOW.isoformat())
    assert stranded.call_args.kwargs["limit"] == pipeline_sweeps.SCAN
    assert pipeline_sweeps.SCAN >= 4 * pipeline_sweeps.BATCH
    assert [i["workflow_id"] for i in items] == [f"exec:{a}:1" for a, _, _ in fresh]


STUCK_ITEM = {"company_id": str(T), "key": f"exec:{A}:2", "action_id": str(A), "draft_version": 2}


def _sweep(settled: list[bool]) -> tuple[MagicMock, MagicMock, MagicMock]:
    tell, settle = MagicMock(), MagicMock(side_effect=settled)
    found = MagicMock(return_value=[STUCK_ITEM] * len(settled))
    with (
        patch.object(wf, "candidates_step", return_value=[]),
        patch.object(wf, "stuck_sends_step", found),
        patch.object(wf, "settle_stuck_step", settle),
        patch.object(wf, "tell_blocked_step", tell),
    ):
        BODY(NOW, None)
    return found, settle, tell


def test_a_settled_stuck_send_is_told_once_under_its_action_version() -> None:
    found, settle, tell = _sweep([True])
    assert found.call_args.args == (NOW.isoformat(),)
    assert settle.call_args.args == (STUCK_ITEM, NOW.isoformat())
    tell.assert_called_once_with(str(A), 2, STUCK)


def test_a_stuck_send_settled_by_someone_else_is_not_told_again() -> None:
    _, _, tell = _sweep([False])
    tell.assert_not_called()


def test_stuck_candidates_are_plain_data_for_the_step_record() -> None:
    found = [StuckSend(T, f"exec:{A}:2", A, 2)]
    with patch.object(wf, "get_engine"), patch.object(stuck, "stuck_sends", return_value=found) as query:
        assert inspect.unwrap(wf.stuck_sends_step)(NOW.isoformat()) == [STUCK_ITEM]
    assert query.call_args.args[1] == NOW


def test_settle_step_rebuilds_the_item() -> None:
    with patch.object(wf, "get_engine"), patch.object(stuck, "settle", return_value=True) as settle:
        assert inspect.unwrap(wf.settle_stuck_step)(STUCK_ITEM, NOW.isoformat())
    assert settle.call_args.args[1:] == (StuckSend(T, f"exec:{A}:2", A, 2), NOW)

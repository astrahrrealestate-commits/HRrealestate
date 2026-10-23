"""`sweep.stranded` body and its candidates step (no DBOS runtime): same ids as the API, known ids skipped."""

import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.contracts import ActionType
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

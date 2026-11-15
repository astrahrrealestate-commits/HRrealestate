"""BRIXX sync bodies (no DBOS runtime): a table the mirror cannot store is skipped as drift, never a run failure."""

import inspect
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from app.channels.brixx.models import BrixxField, BrixxTable
from app.workflows import brixx_sync as wf

CHILD: Callable[[str, str], str] = inspect.unwrap(wf.sync_table)
PARENT: Callable[[datetime, Any], None] = inspect.unwrap(wf.sync_all)
WHEN = datetime(2026, 11, 3, 9, 15, tzinfo=UTC)
LIVE = BrixxTable(
    "PRG_DEMO",
    "ID",
    (BrixxField(1, "ID", "NUMBER", True, None, None), BrixxField(2, "NIEUW", "VARCHAR(5)", False, None, None)),
)
STORED = BrixxTable("PRG_DEMO", "ID", LIVE.fields[:1])


def _begun(stored: BrixxTable | None) -> dict[str, Any]:
    return {
        "company_id": "c1",
        "started_at": WHEN.isoformat(),
        "page": 1,
        "since": None,
        "stored": None if stored is None else asdict(stored),
    }


def test_table_missing_from_the_mirror_is_skipped_without_fetching() -> None:
    with (
        patch.object(wf, "describe_step", return_value=asdict(LIVE)),
        patch.object(wf, "begin_step", return_value=_begun(None)) as begin,
        patch.object(wf, "sync_page_step") as page,
        patch.object(wf, "mark_success_step") as success,
    ):
        assert CHILD("run-1", "PRG_DEMO") == wf.SKIPPED
    assert begin.call_args.args == ("run-1", asdict(LIVE))
    page.assert_not_called()
    success.assert_not_called()


def test_a_table_with_no_resolvable_primary_key_is_skipped_without_beginning_a_run() -> None:
    """`describe_step` returns `None` for a BRIXX `Z*` table whose primary key cannot be resolved (see
    `resolve_primary_key`); the child must skip it exactly like a table missing from the mirror, never call
    `begin_step` (which needs a real table to check), and never fail the run."""
    with (
        patch.object(wf, "describe_step", return_value=None) as describe,
        patch.object(wf, "begin_step") as begin,
        patch.object(wf, "sync_page_step") as page,
        patch.object(wf, "mark_success_step") as success,
    ):
        assert CHILD("run-1", "ZPRG_NOPK") == wf.SKIPPED
    describe.assert_called_once_with("ZPRG_NOPK")
    begin.assert_not_called()
    page.assert_not_called()
    success.assert_not_called()


def test_pages_are_written_through_the_columns_the_mirror_has() -> None:
    with (
        patch.object(wf, "describe_step", return_value=asdict(LIVE)),
        patch.object(wf, "begin_step", return_value=_begun(STORED)),
        patch.object(wf, "sync_page_step", return_value={"has_next": False, "max_upd": None}) as page,
        patch.object(wf, "mark_success_step") as success,
    ):
        assert CHILD("run-1", "PRG_DEMO") == wf.OK
    assert page.call_args.args == ("c1", "run-1", asdict(LIVE), asdict(STORED), 1, None)
    success.assert_called_once()


def _run_parent(outcomes: dict[str, str]) -> MagicMock:
    handles = {name: MagicMock(get_result=MagicMock(return_value=result)) for name, result in outcomes.items()}
    queue = MagicMock()
    queue.enqueue.side_effect = lambda _fn, _run, table: handles[table]
    with (
        patch.object(wf, "company_step", return_value="c1"),
        patch.object(wf, "list_tables_step", return_value=list(outcomes)),
        patch.object(wf, "create_run_step", return_value="run-1"),
        patch.object(wf, "finish_run_step") as finish,
        patch.object(
            wf, "map_after_run"
        ),  # a DBOS workflow call; needs a running DBOS, covered by the integration tests
        patch.object(wf.queues, "brixx_queue", return_value=queue),
        patch.object(wf, "SetWorkflowID"),
    ):
        PARENT(WHEN, None)
    return finish


def test_skipped_tables_do_not_fail_the_run() -> None:
    finish = _run_parent({"PRG_A": wf.OK, "PRG_NEW": wf.SKIPPED})
    finish.assert_called_once_with("c1", "run-1", None)


def test_failed_tables_still_fail_the_run_and_skips_are_not_listed() -> None:
    finish = _run_parent({"PRG_A": "failed:BrixxAuthError", "PRG_NEW": wf.SKIPPED})
    error = finish.call_args.args[2]
    assert error == "tables failed: PRG_A (BrixxAuthError)"

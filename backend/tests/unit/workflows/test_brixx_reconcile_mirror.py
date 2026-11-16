"""brixx.reconcile_table: a table with no resolvable primary key is a no-op success, never a run failure."""

import inspect
from collections.abc import Callable
from unittest.mock import patch

from app.workflows import brixx_reconcile as wf

CHILD: Callable[[str, str], str] = inspect.unwrap(wf.reconcile_table)


def test_a_table_with_no_resolvable_primary_key_is_skipped_without_scanning() -> None:
    """`describe_step` returns `None` for a BRIXX `Z*` table whose primary key cannot be resolved (see
    `resolve_primary_key`): nothing was ever mirrored for it, so there is nothing to reconcile. Must not call
    `reconcile_begin_step`/`scan_step`/`apply_step`, and must still report `ok`, not a failure."""
    with (
        patch.object(wf, "describe_step", return_value=None) as describe,
        patch.object(wf, "reconcile_begin_step") as begin,
        patch.object(wf, "scan_step") as scan,
        patch.object(wf, "apply_step") as apply_,
    ):
        assert CHILD("run-1", "ZPRG_NOPK") == wf.OK
    describe.assert_called_once_with("ZPRG_NOPK")
    begin.assert_not_called()
    scan.assert_not_called()
    apply_.assert_not_called()

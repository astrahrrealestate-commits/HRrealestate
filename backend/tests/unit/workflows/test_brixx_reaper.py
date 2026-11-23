"""Stranded BRIXX workflows: which ones the reaper cancels (pure selection; no DBOS, no DB)."""

from dataclasses import dataclass
from unittest.mock import patch

from app.workflows import brixx_reaper
from app.workflows.brixx_reaper import MAX_CANCELLED, STRANDED_AFTER, stranded_ids

NOW = 2_000_000_000_000
STALE = NOW - int(STRANDED_AFTER.total_seconds() * 1000) - 1
FRESH = NOW - 60_000


@dataclass
class Listed:
    workflow_id: str
    app_version: str | None
    created_at: int | None
    updated_at: int | None


def test_only_old_workflows_of_another_version_are_stranded() -> None:
    found = [
        Listed("old-stale", "aaa", STALE, STALE),
        Listed("old-fresh", "aaa", FRESH, FRESH),  # a rolling deploy's old task still working
        Listed("current-stale", "bbb", STALE, STALE),  # the running version's own backlog is never touched
        Listed("unversioned", None, STALE, STALE),
        Listed("never-updated", "aaa", STALE, None),
    ]
    assert stranded_ids(found, "bbb", NOW) == ["old-stale", "never-updated"]


def test_a_single_run_cancels_at_most_the_cap() -> None:
    found = [Listed(f"w{i}", "aaa", STALE, STALE) for i in range(MAX_CANCELLED + 50)]
    assert len(stranded_ids(found, "bbb", NOW)) == MAX_CANCELLED


def test_the_reaper_lists_both_brixx_queues_and_cancels_what_is_stranded() -> None:
    found = [Listed("old", "aaa", STALE, STALE), Listed("new", "bbb", STALE, STALE)]
    with (
        patch.object(brixx_reaper.DBOS, "list_workflows", return_value=found) as listing,
        patch.object(brixx_reaper.DBOS, "cancel_workflows") as cancel,
        patch.object(brixx_reaper.DBOS, "application_version", "bbb"),
    ):
        assert brixx_reaper.reap_stranded(NOW) == 1
    assert listing.call_args.kwargs["queue_name"] == ["brixx", "brixx_documents"]
    assert listing.call_args.kwargs["status"] == ["PENDING", "ENQUEUED"]
    cancel.assert_called_once_with(["old"])


def test_nothing_stranded_cancels_nothing() -> None:
    with (
        patch.object(brixx_reaper.DBOS, "list_workflows", return_value=[]),
        patch.object(brixx_reaper.DBOS, "cancel_workflows") as cancel,
    ):
        assert brixx_reaper.reap_stranded(NOW) == 0
    cancel.assert_not_called()

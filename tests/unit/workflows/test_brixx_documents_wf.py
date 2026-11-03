"""BRIXX document download workflows: names, ids, retry policy, deps wiring and the enqueue hook (no DBOS, no DB)."""

import inspect
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError, StaleRunError
from app.core.workflow_names import BRIXX_DOCUMENTS_QUEUE, BRIXX_DOWNLOAD_DOCUMENT, brixx_document_workflow_id
from app.db.enums import BrixxDocumentStatus
from app.workflows import brixx_documents, brixx_sync, queues

COMPANY = "018f0000-0000-7000-8000-000000000001"
INFO = {"name": "PRG_DOCUMENT", "primary_key": "PRG_DOCUMENTID", "fields": []}

DOWNLOAD_WF: Callable[[str, int, str], str] = inspect.unwrap(brixx_documents.download_document)
DOWNLOAD_STEP: Callable[[str, int, str], str] = inspect.unwrap(brixx_documents.download_step)
SYNC_PAGES: Callable[[str, str], None] = brixx_sync._sync_pages


def test_names_and_workflow_id_are_fixed() -> None:
    assert (BRIXX_DOCUMENTS_QUEUE, BRIXX_DOWNLOAD_DOCUMENT) == ("brixx_documents", "brixx.download_document")
    assert brixx_document_workflow_id(COMPANY, 42, "v3|u2026", 2) == f"brixxdoc:{COMPANY}:42:v3|u2026:2"


@pytest.mark.parametrize(
    ("error", "retried"),
    [
        (BrixxError("HTTP 503"), True),
        (OperationalError("select", {}, Exception("down")), True),
        (OSError("disk"), True),
        (BrixxAuthError("HTTP 403"), False),
        (StaleRunError("other run"), False),
        (ValueError("bug"), False),
    ],
)
def test_download_step_retries_only_transient_errors(error: BaseException, retried: bool) -> None:
    assert brixx_documents.DOWNLOAD_RETRY["should_retry"](error) is retried


def test_download_step_uses_the_configured_api_storage_and_engine() -> None:
    api, storage, engine = MagicMock(), MagicMock(), MagicMock()
    download = MagicMock(return_value=BrixxDocumentStatus.stored)
    with (
        patch.object(brixx_documents, "brixx_api", return_value=api),
        patch.object(brixx_documents, "get_deps", return_value=MagicMock(storage=storage)),
        patch.object(brixx_documents, "get_engine", return_value=engine),
        patch.object(brixx_documents, "download_version", download),
    ):
        assert DOWNLOAD_STEP(COMPANY, 42, "v1") == "stored"
    session, *args = download.call_args.args
    assert args[:2] == [api, storage]
    assert [str(args[2]), *args[3:]] == [COMPANY, 42, "v1"]
    assert session.bind is engine


def test_workflow_returns_the_step_outcome() -> None:
    failed = MagicMock()
    with (
        patch.object(brixx_documents, "download_step", MagicMock(return_value="forbidden")),
        patch.object(brixx_documents, "failed_step", failed),
    ):
        assert DOWNLOAD_WF(COMPANY, 42, "v1") == "forbidden"
    failed.assert_not_called()


def test_workflow_records_failed_with_the_error_class_only_and_does_not_raise() -> None:
    failed = MagicMock()
    with (
        patch.object(brixx_documents, "download_step", MagicMock(side_effect=BrixxError("token abc in url"))),
        patch.object(brixx_documents, "failed_step", failed),
    ):
        assert DOWNLOAD_WF(COMPANY, 42, "v1") == "failed:BrixxError"
    failed.assert_called_once_with(COMPANY, 42, "v1", "BrixxError")


def test_enqueue_hook_claims_first_then_enqueues_one_deterministic_workflow_per_claim() -> None:
    order = MagicMock()
    order.claim.return_value = [[42, "v1", 1], [43, "v2", 3]]
    queue = MagicMock()
    order.attach_mock(queue.enqueue, "enqueue")
    ids: list[str] = []

    def set_id(workflow_id: str) -> MagicMock:
        ids.append(workflow_id)
        return MagicMock()

    with (
        patch.object(brixx_documents, "claim_documents_step", order.claim),
        patch.object(queues, "brixx_documents_queue", return_value=queue),
        patch.object(brixx_documents, "SetWorkflowID", side_effect=set_id),
    ):
        assert brixx_documents.enqueue_document_downloads(COMPANY, INFO) == 2
    assert order.mock_calls == [
        call.claim(COMPANY, INFO),
        call.enqueue(brixx_documents.download_document, COMPANY, 42, "v1"),
        call.enqueue(brixx_documents.download_document, COMPANY, 43, "v2"),
    ]
    assert ids == [brixx_document_workflow_id(COMPANY, 42, "v1", 1), brixx_document_workflow_id(COMPANY, 43, "v2", 3)]


def _sync_pages_with(table: str) -> MagicMock:
    hook = MagicMock(return_value=0)
    info: dict[str, Any] = {**INFO, "name": table}
    begun = {"company_id": COMPANY, "page": 1, "since": None, "started_at": "2026-11-03T08:00:00+00:00"}
    with (
        patch.object(brixx_sync, "describe_step", MagicMock(return_value=info)),
        patch.object(brixx_sync, "begin_step", MagicMock(return_value=begun)),
        patch.object(brixx_sync, "sync_page_step", MagicMock(return_value={"has_next": False, "max_upd": None})),
        patch.object(brixx_sync, "mark_success_step", MagicMock()),
        patch.object(brixx_sync, "enqueue_document_downloads", hook),
    ):
        SYNC_PAGES("run-1", table)
    return hook


def test_a_synced_document_table_enqueues_downloads() -> None:
    _sync_pages_with("PRG_DOCUMENT").assert_called_once_with(COMPANY, {**INFO, "name": "PRG_DOCUMENT"})


def test_other_tables_enqueue_no_downloads() -> None:
    _sync_pages_with("PRG_DOCUMENTLINK").assert_not_called()


def test_brixx_table_info_round_trips_through_step_json() -> None:
    from dataclasses import asdict

    from app.workflows.brixx_common import info_from_json

    info = BrixxTable("PRG_DOCUMENT", "PRG_DOCUMENTID", (BrixxField(1, "PRG_DOCUMENTID", "NUMBER", True, None, None),))
    assert info_from_json(asdict(info)) == info

"""Finance workflow ids, hook predicates and hook wiring (no DBOS runtime, no database)."""

import inspect
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest

from app.contracts import ActionType
from app.core.errors import AgentFailedError, EstateOSError, PriceSourceNotConfiguredError
from app.core.workflow_names import (
    finance_quote_workflow_id,
    finance_recheck_workflow_id,
    finance_review_id,
    finance_snapshot_workflow_id,
)
from app.finance.triggers import amounts_in, quote_candidate, snapshot_trigger
from app.workflows import finance, pipeline

QUOTE = "0190f000-0000-7000-8000-000000000001"


class _BlipError(EstateOSError):
    retryable = True


def test_workflow_ids_are_deterministic() -> None:
    assert finance_snapshot_workflow_id("a1") == "fin:snap:a1"
    assert finance_quote_workflow_id("m1") == "fin:quote:m1"
    assert finance_recheck_workflow_id("q1", 2) == "fin:recheck:q1:2"


def test_review_id_is_deterministic_per_quote_and_round() -> None:
    first = finance_review_id(QUOTE, 1)
    assert isinstance(first, UUID)
    assert finance_review_id(QUOTE, 1) == first
    assert finance_review_id(UUID(QUOTE), 1) == first  # str or UUID: same id
    assert finance_review_id(QUOTE, 2) != first
    assert finance_review_id("0190f000-0000-7000-8000-000000000002", 1) != first


@pytest.mark.parametrize("kind", list(ActionType))
def test_snapshot_enqueued_only_for_request_contractor(kind: ActionType) -> None:
    assert snapshot_trigger(kind) is (kind is ActionType.request_contractor)


@pytest.mark.parametrize(
    ("inbound", "contractor", "amounts", "attachments", "wanted"),
    [
        (True, True, 1, 0, True),
        (True, True, 0, 2, True),
        (True, True, 3, 1, True),
        (True, True, 0, 0, False),  # a contractor chatting without an amount or a file is no quote
        (True, False, 1, 1, False),  # a tenant mentioning an amount is no quote
        (False, True, 1, 1, False),  # our own outbound message is never reviewed
    ],
)
def test_quote_enqueued_only_for_contractor_with_amount_or_attachment(
    inbound: bool, contractor: bool, amounts: int, attachments: int, wanted: bool
) -> None:
    assert quote_candidate(inbound=inbound, contractor=contractor, amounts=amounts, attachments=attachments) is wanted


@pytest.mark.parametrize(
    ("body", "n"),
    [
        ({"entities": {"amounts": [{"amount": "131.00", "currency": "EUR"}]}}, 1),
        ({"entities": {"amounts": []}}, 0),
        ({"entities": {}}, 0),
        ({}, 0),
        ({"entities": {"amounts": "not a list"}}, 0),
        (None, 0),
    ],
)
def test_amounts_in_tolerates_any_stored_body(body: Any, n: int) -> None:
    assert amounts_in(body) == n


def _hook(trigger: MagicMock, enqueue: MagicMock) -> None:
    with (
        patch.object(finance, "snapshot_trigger_step", trigger),
        patch.object(finance, "enqueue_snapshot", enqueue),
    ):
        finance.snapshot_after_approval("act-1")


def test_approval_hook_enqueues_the_snapshot_for_a_request_contractor() -> None:
    enqueue = MagicMock()
    _hook(MagicMock(return_value="co-1"), enqueue)
    enqueue.assert_called_once_with("co-1", "act-1")


def test_approval_hook_skips_other_actions() -> None:
    enqueue = MagicMock()
    _hook(MagicMock(return_value=None), enqueue)
    enqueue.assert_not_called()


def test_approval_hook_failure_never_fails_the_parent() -> None:
    enqueue = MagicMock()
    _hook(MagicMock(side_effect=RuntimeError("db down")), enqueue)  # no exception escapes
    enqueue.assert_not_called()


def _quote_hook(candidate: MagicMock, enqueue: MagicMock) -> None:
    with patch.object(finance, "quote_candidate_step", candidate), patch.object(finance, "enqueue_quote", enqueue):
        finance.quote_after_understanding("co-1", "msg-1")


def test_quote_hook_enqueues_only_a_candidate() -> None:
    yes, no = MagicMock(), MagicMock()
    _quote_hook(MagicMock(return_value=True), yes)
    _quote_hook(MagicMock(return_value=False), no)
    yes.assert_called_once_with("co-1", "msg-1")
    no.assert_not_called()


def test_quote_hook_failure_never_fails_the_pipeline() -> None:
    enqueue = MagicMock()
    _quote_hook(MagicMock(side_effect=RuntimeError("db down")), enqueue)
    enqueue.assert_not_called()


@pytest.mark.parametrize(
    ("helper", "args", "workflow_id"),
    [
        (finance.enqueue_snapshot, ("co", "a1"), "fin:snap:a1"),
        (finance.enqueue_quote, ("co", "m1"), "fin:quote:m1"),
        (finance.enqueue_recheck, ("co", "q1", 3), "fin:recheck:q1:3"),
    ],
)
def test_enqueue_helpers_use_the_deterministic_id_on_the_finance_queue(
    helper: Callable[..., bool], args: tuple[Any, ...], workflow_id: str
) -> None:
    queue, set_id = MagicMock(), MagicMock()
    with (
        patch.object(finance.queues, "finance_queue", return_value=queue),
        patch.object(finance, "SetWorkflowID", set_id),
    ):
        assert helper(*args) is True
    set_id.assert_called_once_with(workflow_id)
    queue.enqueue.assert_called_once()


def test_an_enqueue_failure_is_logged_and_never_raised() -> None:
    queue = MagicMock()
    queue.enqueue.side_effect = RuntimeError("system db down")
    with patch.object(finance.queues, "finance_queue", return_value=queue), patch.object(finance, "log") as log:
        assert finance.enqueue_snapshot("co", "a1") is False
        assert finance.enqueue_quote("co", "m1") is False
    assert [c.kwargs["workflow_id"] for c in log.error.call_args_list] == ["fin:snap:a1", "fin:quote:m1"]
    assert all("system db down" not in str(c) for c in log.error.call_args_list)  # type only, never the text


SNAPSHOT_WF: Callable[[str], int | None] = inspect.unwrap(finance.snapshot_wf)
QUOTE_STEP: Callable[[str], str | None] = inspect.unwrap(finance.quote_step)


def test_snapshot_workflow_stops_when_there_is_nothing_to_snapshot() -> None:
    step = MagicMock()
    with (
        patch.object(finance, "snapshot_target_step", MagicMock(return_value=None)),
        patch.object(finance, "snapshot_step", step),
    ):
        assert SNAPSHOT_WF("a1") is None
    step.assert_not_called()


def test_snapshot_workflow_runs_the_snapshot_for_the_actions_vendor() -> None:
    step = MagicMock(return_value=2)
    with (
        patch.object(finance, "snapshot_target_step", MagicMock(return_value=["co", "ven"])),
        patch.object(finance, "snapshot_step", step),
    ):
        assert SNAPSHOT_WF("a1") == 2
    step.assert_called_once_with("a1", "co", "ven")


@pytest.mark.parametrize("error", [PriceSourceNotConfiguredError("web"), AgentFailedError("quote_reader: x")])
def test_a_permanent_finance_error_is_logged_once_not_retried(error: EstateOSError) -> None:
    with (
        patch.object(finance, "review_message", MagicMock(side_effect=error)),
        patch.object(finance, "get_engine"),
        patch.object(finance, "get_settings"),
        patch.object(finance, "log") as log,
    ):
        assert QUOTE_STEP(QUOTE) is None
    log.warning.assert_called_once()
    assert log.warning.call_args.kwargs["reason"] == type(error).__name__


def test_a_retryable_finance_error_propagates_for_the_step_retry() -> None:
    with (
        patch.object(finance, "review_message", MagicMock(side_effect=_BlipError("503"))),
        patch.object(finance, "get_engine"),
        patch.object(finance, "get_settings"),
        pytest.raises(_BlipError),
    ):
        QUOTE_STEP(QUOTE)


def test_the_steps_only_retry_transient_errors() -> None:
    should_retry = finance.STEP_RETRY["should_retry"]
    assert should_retry(_BlipError("503")) is True
    assert should_retry(PriceSourceNotConfiguredError("web")) is False


AFTER: Callable[[str, bool], bool] = pipeline._after_understanding


def test_pipeline_runs_the_quote_hook_last_and_keeps_its_result() -> None:
    order = MagicMock()
    with (
        patch.object(pipeline, "resolve_step", order.resolve),
        patch.object(pipeline, "link_step", MagicMock(return_value="case-1")),
        patch.object(pipeline, "company_step", MagicMock(return_value="co-1")),
        patch.object(pipeline, "propose_step", MagicMock(return_value={"approval_ids": [], "exceptions": []})),
        patch.object(pipeline, "attachments_step", MagicMock(return_value=["att-1"])),
        patch.object(pipeline, "enqueue_filing", order.file),
        patch.object(pipeline, "quote_after_understanding", order.quote),
    ):
        assert AFTER("msg-1", False) is True
    assert order.mock_calls == [call.resolve("msg-1"), call.file("co-1", "att-1"), call.quote("co-1", "msg-1")]

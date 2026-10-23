import pytest
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.errors import AgentFailedError
from app.workflows.concierge import TURN_RETRY, turn_retryable
from app.workflows.retry import STEP_RETRY, retryable


@pytest.mark.parametrize(
    "exc",
    [
        InterfaceError("select", {}, Exception("gone")),
        PoolTimeoutError("pool exhausted"),
        OSError("reset"),
        OperationalError("select", {}, Exception("down")),
    ],
)
def test_turn_step_retries_what_run_turn_reraises(exc: BaseException) -> None:
    assert turn_retryable(exc)


def test_pool_timeout_is_only_retried_by_the_turn_policy() -> None:
    exc = PoolTimeoutError("pool exhausted")
    assert not retryable(exc)  # the global policy is unchanged
    assert turn_retryable(exc)


@pytest.mark.parametrize(
    "exc", [ValueError("bad"), AgentFailedError("x"), IntegrityError("insert", {}, Exception("dup"))]
)
def test_data_errors_are_not_retried(exc: BaseException) -> None:
    assert not turn_retryable(exc)


def test_turn_policy_keeps_the_shared_limits() -> None:
    assert TURN_RETRY["should_retry"] is turn_retryable
    assert {k: v for k, v in TURN_RETRY.items() if k != "should_retry"} == {
        k: v for k, v in STEP_RETRY.items() if k != "should_retry"
    }

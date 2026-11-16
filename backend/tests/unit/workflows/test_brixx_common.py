"""brixx_retryable: BRIXX step retry policy excludes errors another attempt cannot fix."""

import pytest

from app.core.errors import BrixxAuthError, BrixxError, BrixxNotFoundError, StaleRunError
from app.workflows.brixx_common import brixx_retryable


@pytest.mark.parametrize("exc", [BrixxAuthError("denied"), BrixxNotFoundError("missing"), StaleRunError("stale")])
def test_unfixable_errors_are_not_retried(exc: BrixxError) -> None:
    assert brixx_retryable(exc) is False


def test_a_generic_brixx_error_is_retried() -> None:
    assert brixx_retryable(BrixxError("transient")) is True


def test_a_non_brixx_exception_is_not_retried() -> None:
    assert brixx_retryable(ValueError("unrelated")) is False

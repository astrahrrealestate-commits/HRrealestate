import pytest
from pydantic import ValidationError

from app.contracts import CaseSummary


def test_case_summary_valid() -> None:
    s = CaseSummary(summary="Tenant reports water leak in bathroom.", next_step="Send plumber")
    assert s.summary == "Tenant reports water leak in bathroom."
    assert s.next_step == "Send plumber"


def test_case_summary_blank_rejected() -> None:
    with pytest.raises(ValidationError):
        CaseSummary(summary="   ", next_step="ok")

    with pytest.raises(ValidationError):
        CaseSummary(summary="ok", next_step="   ")


def test_case_summary_length_limits() -> None:
    with pytest.raises(ValidationError):
        CaseSummary(summary="a" * 1201, next_step="ok")

    with pytest.raises(ValidationError):
        CaseSummary(summary="ok", next_step="b" * 201)

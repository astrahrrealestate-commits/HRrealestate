import pytest
from pydantic import ValidationError

from app.contracts import OwnerAnswer


def test_answer_length_and_blank() -> None:
    assert OwnerAnswer(answer="x" * 1500, case_refs=[]).answer
    for bad in ("", "  ", "x" * 1501):
        with pytest.raises(ValidationError):
            OwnerAnswer(answer=bad, case_refs=[])

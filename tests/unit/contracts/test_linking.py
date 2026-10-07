from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.contracts import LinkDecision


def test_link_decision_valid() -> None:
    case_id = uuid4()
    decision = LinkDecision(case_id=case_id, reason="Same tenant and leak topic", confidence=0.85)
    assert decision.case_id == case_id
    assert decision.confidence == 0.85


def test_link_decision_null_case_valid() -> None:
    decision = LinkDecision(case_id=None, reason="New maintenance issue", confidence=0.5)
    assert decision.case_id is None


def test_link_decision_blank_reason_rejected() -> None:
    with pytest.raises(ValidationError):
        LinkDecision(case_id=uuid4(), reason="   ", confidence=0.8)


def test_link_decision_confidence_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        LinkDecision(case_id=uuid4(), reason="ok", confidence=1.1)

    with pytest.raises(ValidationError):
        LinkDecision(case_id=uuid4(), reason="ok", confidence=-0.1)


def test_link_decision_reason_too_long() -> None:
    with pytest.raises(ValidationError):
        LinkDecision(case_id=uuid4(), reason="x" * 301, confidence=0.8)

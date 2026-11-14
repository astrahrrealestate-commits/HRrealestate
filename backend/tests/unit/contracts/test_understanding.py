from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.contracts import Category, Entities, Money, Suspicious, Understanding, Urgency


def _u(**kw: Any) -> Understanding:
    base: dict[str, Any] = {
        "category": Category.maintenance,
        "intent": "report broken heating",
        "urgency": Urgency.high,
        "requires_reply": True,
        "entities": Entities.none(),
        "suspicious": Suspicious(flag=False, reason=None),
        "confidence": 0.9,
        "prompt_version": "understanding/v2",
    }
    return Understanding(**{**base, **kw})


def test_round_trip_with_entities() -> None:
    e = Entities(
        people=["Tenant 1"],
        unit_refs=["Whg 3"],
        dates=["2026-01-02", "nächste Woche"],  # PR #15 contract: dates are the text the message used
        amounts=[Money(amount=Decimal("850.00"), currency="EUR")],
    )
    u = _u(entities=e)
    assert Understanding.model_validate_json(u.model_dump_json()) == u


@pytest.mark.parametrize(("flag", "reason"), [(True, None), (True, ""), (True, "   "), (False, "why")])
def test_suspicious_reason_iff_flag(flag: bool, reason: str | None) -> None:
    with pytest.raises(ValidationError):
        Suspicious(flag=flag, reason=reason)


@pytest.mark.parametrize(
    "kw",
    [
        {"confidence": 1.1},
        {"confidence": -0.1},
        {"intent": "x" * 201},
        {"intent": " "},
        {"prompt_version": "v1"},
        {"prompt_version": "u/v\u0661"},
    ],
)
def test_bounds(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _u(**kw)


@pytest.mark.parametrize("kw", [{"amount": Decimal("1.234"), "currency": "EUR"}, {"amount": 1, "currency": "eur"}])
def test_money_bounds(kw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Money(**kw)


def test_entities_required_for_llm() -> None:
    with pytest.raises(ValidationError):
        Entities()  # type: ignore[call-arg]

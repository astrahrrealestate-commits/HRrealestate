"""A model's `sender_role` is kept only when the prompt asked for it and nothing flagged the mail."""

from typing import Any

from app.contracts import Category, Entities, SenderRole, Suspicious, Understanding, Urgency
from app.pipeline.understand import settle_sender_role


def _und(role: SenderRole | None = SenderRole.legal, **kw: Any) -> Understanding:
    base: dict[str, Any] = {
        "category": Category.administration,
        "intent": "Letter from a lawyer",
        "urgency": Urgency.normal,
        "requires_reply": True,
        "entities": Entities.none(),
        "suspicious": Suspicious(flag=False, reason=None),
        "confidence": 0.9,
        "sender_role": role,
        "prompt_version": "understanding/v3",
    }
    return Understanding(**{**base, **kw})


def test_a_prompt_that_never_described_the_field_leaves_no_role() -> None:
    """v1 and v2 ship the same output schema but never explain `sender_role`: what the model put there is a guess."""
    assert settle_sender_role(_und(), prompted=False, scanner_flagged=False).sender_role is None


def test_a_prompted_role_is_kept() -> None:
    assert settle_sender_role(_und(), prompted=True, scanner_flagged=False).sender_role is SenderRole.legal


def test_a_mail_the_injection_scanner_flagged_loses_its_role() -> None:
    """The scanner flips `suspicious` after the model answered, which the contract validator never sees."""
    assert settle_sender_role(_und(), prompted=True, scanner_flagged=True).sender_role is None


def test_nothing_changes_when_there_is_no_role_to_drop() -> None:
    und = _und(None)
    assert settle_sender_role(und, prompted=False, scanner_flagged=True) is und

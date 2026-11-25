"""Understandings stored before a field existed still read: the shim adds what the contract now requires."""

from typing import Any

from app.contracts import Understanding
from app.pipeline.propose import _with_defaults

OLD_BODY: dict[str, Any] = {
    "category": "maintenance",
    "intent": "Leak",
    "urgency": "high",
    "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
    "suspicious": {"flag": False, "reason": None},
    "confidence": 0.9,
    "prompt_version": "understanding/v1",
}


def test_a_body_from_before_requires_reply_and_sender_role_still_validates() -> None:
    und = Understanding.model_validate(_with_defaults(OLD_BODY))
    assert (und.requires_reply, und.sender_role) == (True, None)


def test_spam_stored_before_requires_reply_needs_no_answer() -> None:
    assert Understanding.model_validate(_with_defaults({**OLD_BODY, "category": "spam"})).requires_reply is False


def test_stored_values_win_over_the_defaults() -> None:
    body = {**OLD_BODY, "requires_reply": False, "sender_role": "legal"}
    und = Understanding.model_validate(_with_defaults(body))
    assert (und.requires_reply, und.sender_role.value if und.sender_role else None) == (False, "legal")

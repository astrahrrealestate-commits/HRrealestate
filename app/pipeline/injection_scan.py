"""Deterministic prompt-injection scan of inbound text. A second opinion next to the model's own `suspicious` flag:
the model can be talked out of flagging, this cannot. A hit sets `Understanding.suspicious`, which the rules engine
turns into an exception for Harjot (no draft is ever auto-approved). Pure: no I/O."""

import re

_FLAGS = re.IGNORECASE | re.DOTALL
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "tries to override instructions",
        re.compile(
            r"\b(ignore|disregard|forget|negeer|vergeet)\b.{0,30}\b(previous|prior|above|earlier|vorige|eerdere)\b"
            r".{0,30}\b(instructions?|prompts?|rules?|instructies|regels)\b",
            _FLAGS,
        ),
    ),
    ("claims a new role", re.compile(r"\b(you are now|new instructions?|system prompt|developer mode)\b", _FLAGS)),
    (
        "forged prompt delimiter",
        re.compile(
            r"[<\uff1c\ufe64]\s*/?\s*(message|data|system|assistant|instructions?)(?=[\s/>\uff1e\ufe65])", _FLAGS
        ),
    ),
    (
        "payment details change",
        re.compile(
            r"\b(nieuwe?|gewijzigde?|new|changed|updated)\b.{0,40}\b(iban|bankrekening|rekeningnummer|bank account)\b",
            _FLAGS,
        ),
    ),
    ("hidden direction control characters", re.compile("[\u202a-\u202e\u2066-\u2069]")),
    ("hidden zero-width run", re.compile("[\u200b\u2060\ufeff]{3,}")),
)


def scan(text: str) -> str | None:
    """A short reason when the text looks like an injection attempt, else None."""
    for reason, pattern in _PATTERNS:
        if pattern.search(text):
            return reason
    return None

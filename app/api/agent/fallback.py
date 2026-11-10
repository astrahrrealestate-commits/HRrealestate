"""What the Super Agent says when the model could not answer.

Only a question that really asks about open work gets the live case list; everything else gets an honest "I can't
answer that right now". Nothing here states a fact about a tenant, unit or contractor.
"""

import re

_OPEN_WORK = re.compile(
    r"\b(open|active|pending|outstanding)\s+(cases?|tickets?|requests?|issues?|jobs?)\b"
    r"|\bwhat(?:'s|\s+is)\s+open\b"
    r"|\b(?:cases?|tickets?)\s+(?:status|overview)\b",
    re.IGNORECASE,
)

_DEGRADED = (
    "⚠️ **Assistant degraded:** I can't answer that reliably right now (the AI model timed out or was "
    "rate-limited). No automated actions were performed. Please try again in a moment."
)
_NO_ANSWER = "I can't answer that reliably right now. No automated actions were performed."


def domain_fallback_answer(query: str, live_cases_text: str = "", is_error: bool = False) -> str:
    """The case list for a question about open work, otherwise a plain statement that no answer could be given."""
    if _OPEN_WORK.search(query):
        has_cases = bool(live_cases_text) and "no active open" not in live_cases_text.lower()
        if has_cases and "0 active open" not in live_cases_text.lower():
            return f"**Open cases in the database:**\n\n{live_cases_text}"
        return "**Open cases:** 0 open cases found in the database."
    return _DEGRADED if is_error else _NO_ANSWER

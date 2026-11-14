"""Do not answer rent questions from data that does not exist.

No rent or payment table is mirrored yet (app/core/rent_data.py), so "0 payments" or "0 matching entries" for
"who is overdue" would read as "nobody is". Those questions get an honest answer instead.
"""

import re

from app.core.rent_data import RENT_DATA_AVAILABLE

NO_RENT_DATA_ANSWER = (
    "I don't have rent or payment data yet, so I can't say who is overdue or what has been paid. Rent amounts and "
    "payments arrive with the BRIXX rent sync; until then I won't guess."
)

_RENT_MONEY_QUESTION = re.compile(
    r"\b(overdue|arrears?|unpaid|owes?|owed)\b"
    r"|\bwho\s+(?:has\s+|have\s+)?paid\b"
    r"|\bpayments?\s+(?:recorded|received|made|this|last)\b"
    r"|\b(?:number|count)\s+of\s+payments\b"
    r"|\bhow\s+many\s+payments\b"
    r"|\bcollection\s+rate\b"
    r"|\brent\s+(?:outstanding|collected|received|roll|status)\b"
    r"|\b(?:outstanding|open)\s+rent\b"
    r"|\bhow\s+much\s+rent\b"
    r"|\bbehind\s+(?:on|with)\s+(?:the\s+|their\s+)?rent\b",
    re.IGNORECASE,
)


def rent_data_answer(query: str) -> str | None:
    """The no-data answer for a question about who owes or paid rent, while no rent data is mirrored."""
    if RENT_DATA_AVAILABLE or not _RENT_MONEY_QUESTION.search(query):
        return None
    return NO_RENT_DATA_ANSWER

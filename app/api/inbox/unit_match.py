"""Which of the company's own units a thread names, for a case that has no unit recorded."""

import re
from collections.abc import Sequence


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def unit_named_in(text: str, units: Sequence[tuple[str, str | None]]) -> str | None:
    """The display label (address, else label) of the one unit whose label appears in `text`.

    `units` are (label, address) pairs of the company. Several different units named, or none, answer None: a
    thread is never assigned to a unit by a guess.
    """
    haystack = _normal(text)
    found = {
        address or label
        for label, address in units
        if re.search(rf"(?<![\w-]){re.escape(_normal(label))}(?![\w-])", haystack)
    }
    return found.pop() if len(found) == 1 else None

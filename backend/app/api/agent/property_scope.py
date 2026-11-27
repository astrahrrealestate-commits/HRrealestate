"""Scope a Super Agent question to the property it names.

A question like "tickets for Prinsengracht" must be answered for that street, and one naming a street the company
does not have must say so, instead of listing the portfolio's top cases. Streets are recognised by their Dutch
suffix; a question that names none is not scoped.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.llm.agents.owner_qa import CaseBrief

_STREET = re.compile(
    r"\b([a-zà-ÿ]+(?:gracht|straat|laan|weg|plein|singel|kade|dijk|steeg|hof|dreef|pad|allee|park|markt|wal|veld|haven|veste|plantsoen|passage|baan))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PropertyScope:
    kind: Literal["none", "scoped", "unknown"]
    street: str = ""  # the first named street the portfolio does not have (kind "unknown")
    briefs: tuple[CaseBrief, ...] = ()  # the cases of the named property (kind "scoped")


def property_scope(query: str, units: Sequence[tuple[str, str | None]], briefs: Sequence[CaseBrief]) -> PropertyScope:
    """`units` are the company's (label, address) pairs; `briefs` its case summaries (labels carry the address)."""
    streets = list(dict.fromkeys(m.lower() for m in _STREET.findall(query)))
    if not streets:
        return PropertyScope("none")
    lowered = query.lower()
    matched = [(label, address) for label, address in units if any(s in label.lower() for s in streets)]
    if not matched:
        return PropertyScope("unknown", street=streets[0].capitalize())
    exact = [u for u in matched if u[0].lower() in lowered]
    wanted = [label.lower() for label, _ in (exact or matched)]
    return PropertyScope("scoped", briefs=tuple(b for b in briefs if any(w in b.label.lower() for w in wanted)))

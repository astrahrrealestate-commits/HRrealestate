"""Which property and case a scheduling request names. Only what the owner wrote counts: no match, no guess."""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import CaseState
from app.db.models import Case, Unit

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def unit_named(session: Session, company_id: UUID, query: str) -> Unit | None:
    """The one unit whose address or label the query names best; None when none or several are equally close."""
    wanted = _tokens(query)
    scored: list[tuple[int, Unit]] = []
    for unit in session.scalars(select(Unit).where(Unit.company_id == company_id, Unit.valid_to.is_(None))).all():
        words = _tokens(unit.address or unit.label or "")
        hits = len(words & wanted)
        if words and hits and any(len(w) >= 5 for w in words & wanted):
            scored.append((hits, unit))
    if not scored:
        return None
    best = max(hits for hits, _ in scored)
    top = [unit for hits, unit in scored if hits == best]
    return top[0] if len(top) == 1 else None


def open_case_on(session: Session, company_id: UUID, unit: Unit) -> Case | None:
    """The unit's single open case, or None when it has none or several (we do not pick one)."""
    cases = session.scalars(
        select(Case).where(
            Case.company_id == company_id,
            Case.unit_id == unit.id,
            Case.state.notin_([CaseState.resolved, CaseState.closed]),
        )
    ).all()
    return cases[0] if len(cases) == 1 else None

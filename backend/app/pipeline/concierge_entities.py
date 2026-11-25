"""Who, where and which case an owner question means, so the planner can name cases beyond its brief. Deterministic and
free: `rapidfuzz` and the glossary over the company's own rows (invariant 4). Names may come from mail headers, so they
are untrusted: one line each, contact details redacted, rendered only inside a data block. Ids come from the rows."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.property_terms import ITEM_TERMS, canonical_tokens, fold, normalise_item_key
from app.db.enums import PersonKind
from app.db.models import Case, Person, Unit
from app.pipeline.case_repo import OPEN_STATES
from app.pipeline.concierge_sanitize import plain_line, redact_contact

LIMIT = 5
MAX_NAME = 80
MAX_CASE_ROWS = 60  # newest cases of the resolved people and units that are ranked
FULL, TRADE = 100.0, 60.0
TYPO_CUTOFF, TYPO_MIN_CHARS = 80.0, 5  # a short word must match exactly: `Jan` is not `Dan`
_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_POSSESSIVE = re.compile(r"['’]s\b")
# Name particles, titles and question words never identify anyone on their own.
_IGNORED = frozenset(
    [
        "van",
        "der",
        "den",
        "het",
        "een",
        "ter",
        "ten",
        "tot",
        "bij",
        "aan",
        "wat",
        "wie",
        "waar",
        "hoe",
        "mevrouw",
        "meneer",
        "heer",
        "mrs",
        "mr",
        "ms",
        "the",
        "and",
        "for",
        "with",
        "what",
        "who",
        "where",
        "when",
        "which",
        "did",
        "does",
        "has",
        "have",
        "say",
        "said",
        "show",
        "tell",
        "about",
        "from",
        "this",
        "that",
        "all",
        "any",
        "first",
        "today",
    ]
)


@dataclass(frozen=True)
class Entity:
    id: UUID
    label: str


@dataclass(frozen=True)
class Entities:
    people: tuple[Entity, ...]
    units: tuple[Entity, ...]
    cases: tuple[Entity, ...]

    @property
    def case_ids(self) -> frozenset[UUID]:
        return frozenset(c.id for c in self.cases)

    def render(self) -> str:
        lines = [f"person: {p.id} | {p.label}" for p in self.people]
        lines += [f"unit: {u.id} | {u.label}" for u in self.units]
        lines += [f"case: {c.id} | {c.label}" for c in self.cases]
        return "\n".join(lines)


NO_ENTITIES = Entities((), (), ())


def _label(text: str) -> str:
    return redact_contact(plain_line(text))[:MAX_NAME].replace("|", "/")


def _words(text: str) -> list[str]:
    return [w for w in _WORD.findall(fold(_POSSESSIVE.sub("", text))) if len(w) >= 3 and w not in _IGNORED]


def _same_word(a: str, b: str) -> float:
    if a == b:
        return FULL
    if min(len(a), len(b)) < TYPO_MIN_CHARS:
        return 0.0
    score = fuzz.ratio(a, b)
    return score if score >= TYPO_CUTOFF else 0.0


def _overlap(wanted: list[str], words: list[str]) -> float:
    return sum(max((_same_word(w, q) for q in words), default=0.0) for w in wanted)


def _trades(question: str) -> frozenset[str]:
    keys = {normalise_item_key(w) for w in [question, *_words(question)]}
    return frozenset(keys & ITEM_TERMS.keys())


def _people(session: Session, company_id: UUID, question: str, words: list[str], limit: int) -> list[Person]:
    trades = _trades(question)
    scored: list[tuple[float, Person]] = []
    for person in session.scalars(select(Person).where(Person.company_id == company_id)):
        score = _overlap(_words(person.display_name), words)
        if person.kind is PersonKind.contractor and person.trade and normalise_item_key(person.trade) in trades:
            score += TRADE
        if score:
            scored.append((score, person))
    scored.sort(key=lambda p: (-p[0], p[1].valid_to is not None, p[1].id))
    return [p for _, p in scored[:limit]]


def _numbers(text: str) -> set[str]:
    return {w for w in _WORD.findall(fold(text)) if any(c.isdigit() for c in w)}


def _units(session: Session, company_id: UUID, question: str, words: list[str], limit: int) -> list[Unit]:
    """The units of a named street; when the question also names a house number the street has, only that one."""
    street_words = [w for w in words if not any(c.isdigit() for c in w)]
    rows = session.scalars(select(Unit).where(Unit.company_id == company_id).order_by(Unit.label, Unit.id))
    named = [u for u in rows if _overlap([w for w in _words(u.label) if not any(c.isdigit() for c in w)], street_words)]
    asked = _numbers(question)
    exact = [u for u in named if asked & _numbers(u.label)]
    return (exact or named)[:limit]


def _cases(
    session: Session, company_id: UUID, question: str, people: Iterable[Person], units: Iterable[Unit], limit: int
) -> list[Case]:
    person_ids, unit_ids = [p.id for p in people], [u.id for u in units]
    if not person_ids and not unit_ids:
        return []
    rows = session.scalars(
        select(Case)
        .where(Case.company_id == company_id, or_(Case.primary_person_id.in_(person_ids), Case.unit_id.in_(unit_ids)))
        .order_by(Case.opened_at.desc(), Case.id.desc())
        .limit(MAX_CASE_ROWS)
    )
    wanted = set(canonical_tokens(question))
    ranked = sorted(  # stable: newest first within equal fit
        rows, key=lambda c: (-len(wanted & set(canonical_tokens(c.summary))), c.state not in OPEN_STATES)
    )
    return ranked[:limit]


def resolve_entities(session: Session, company_id: UUID, question: str, limit: int = LIMIT) -> Entities:
    words = _words(question)
    if not words:
        return NO_ENTITIES
    people = _people(session, company_id, question, words, limit)
    units = _units(session, company_id, question, words, limit)
    cases = _cases(session, company_id, question, people, units, limit)
    return Entities(
        tuple(Entity(p.id, _label(p.display_name)) for p in people),
        tuple(Entity(u.id, _label(u.label)) for u in units),
        tuple(Entity(c.id, f"{c.state.value} | {_label(c.summary)}") for c in cases),
    )

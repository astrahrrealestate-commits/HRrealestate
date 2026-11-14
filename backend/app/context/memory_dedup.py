"""Write-time duplicate detection for memory items (hygiene before the owner review queue).

Two texts count as the same rule only when they are identical once case, punctuation, spacing and articles are
ignored. There is deliberately no fuzzy similarity: one flipped word ("under" / "over", "before" / "after", a contractor
name) is a different rule, and a wrong merge silently drops the owner's rule. A missed duplicate costs one extra card.
"""

import re
from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import MemoryKind, MemoryOrigin, MemoryScope, MemoryStatus
from app.db.models import MemoryItem

MAX_CANDIDATES = 200  # past this many items in one scope the lookup stops matching, which fails safe (no merge)

_WORD = re.compile(r"\w+", re.UNICODE)
_ARTICLES = frozenset({"the", "a", "an", "de", "het", "een"})


def _words(text: str) -> tuple[str, ...]:
    return tuple(w for w in _WORD.findall(text.casefold()) if w not in _ARTICLES)


def is_near_duplicate(a: str, b: str) -> bool:
    """True when `a` and `b` are the same rule up to case, punctuation, spacing and articles."""
    words = _words(a)
    return bool(words) and words == _words(b)


def find_near_duplicate(
    session: Session,
    company_id: UUID,
    scope: MemoryScope,
    scope_id: UUID | None,
    text: str,
    statuses: Iterable[MemoryStatus],
    *,
    kind: MemoryKind | None = None,
    origin: MemoryOrigin | None = None,
) -> MemoryItem | None:
    """The most-evidenced existing item in the same company and scope that restates `text`.

    `kind` and `origin`, when given, must match: a model-proposed item never absorbs an owner's rule or the reverse.
    """
    query = select(MemoryItem).where(
        MemoryItem.company_id == company_id,
        MemoryItem.scope == scope,
        MemoryItem.scope_id == scope_id,
        MemoryItem.status.in_(tuple(statuses)),
    )
    if kind is not None:
        query = query.where(MemoryItem.kind == kind)
    if origin is not None:
        query = query.where(MemoryItem.origin == origin)
    candidates: Sequence[MemoryItem] = session.scalars(
        query.order_by(MemoryItem.evidence_count.desc(), MemoryItem.created_at.desc()).limit(MAX_CANDIDATES)
    ).all()
    return next((item for item in candidates if is_near_duplicate(item.text, text)), None)

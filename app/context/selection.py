"""Which open cases get full detail in a prompt (spec: 2026-10-23-agent-memory-context-design §7).

A model that is handed every open case in full loses the one the owner asked about. So cases are ranked by relevance
to the question (the thread's focus case, a ticket id or name in the question, then urgency) and only the top few carry
a summary; the rest stay in the prompt as one-line index entries, so none disappears and the model can ask for more.
Deterministic and free: no model call, no embedding lookup.
"""

import re
from collections.abc import Sequence
from uuid import UUID

from app.llm.agents.owner_qa import CaseBrief

DETAIL_CASES = 5  # cases that keep a summary; the rest are index lines
SUMMARY_CHARS = 400
LIST_CHARS = 5500  # the case listing of one prompt; leaves room for tasks inside the 8000-char data block
NOTE_RESERVE = 120  # room kept for the closing count note

_FOCUS_SCORE = 1000
_ID_SCORE = 500
_LABEL_HIT = 20
_SUMMARY_HIT = 5
_URGENCY_RANK = {"emergency": 0, "high": 1, "normal": 2, "low": 3}
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    [
        "about",
        "after",
        "again",
        "also",
        "been",
        "being",
        "case",
        "cases",
        "could",
        "does",
        "from",
        "have",
        "into",
        "issue",
        "issues",
        "just",
        "more",
        "need",
        "open",
        "please",
        "show",
        "some",
        "status",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "ticket",
        "tickets",
        "tell",
        "what",
        "when",
        "where",
        "which",
        "will",
        "with",
        "would",
        "update",
        "updates",
    ]
)


def _words(text: str) -> set[str]:
    """Words of 4+ letters, plus any shorter token with a digit (house numbers, unit codes like `42` or `9f`)."""
    tokens = _WORD.findall(text.lower())
    return {t for t in tokens if len(t) >= 4 or any(ch.isdigit() for ch in t)} - _STOPWORDS


def _score(case: CaseBrief, query: str, query_words: set[str], focus: str) -> int:
    score = _FOCUS_SCORE if focus and str(case.case_id) == focus else 0
    cid = str(case.case_id).lower()
    if cid in query or cid[:6] in query:
        score += _ID_SCORE
    score += _LABEL_HIT * len(query_words & _words(case.label))
    score += _SUMMARY_HIT * len(query_words & _words(case.summary))
    return score


def rank_cases(cases: Sequence[CaseBrief], query: str, focus_case_id: UUID | str | None = None) -> list[CaseBrief]:
    """Most relevant first: focus case, named in the question, then urgency. Stable for ties."""
    q = query.lower()
    q_words = _words(q)
    focus = str(focus_case_id) if focus_case_id else ""
    keyed = [
        (-_score(c, q, q_words, focus), _URGENCY_RANK.get((c.urgency or "").lower(), 4), i, c)
        for i, c in enumerate(cases)
    ]
    return [c for *_, c in sorted(keyed, key=lambda k: k[:3])]


def render_case_lines(cases: Sequence[CaseBrief], detail: int = DETAIL_CASES, max_chars: int = LIST_CHARS) -> list[str]:
    """The first `detail` cases with a clipped summary, the rest as index lines, all within `max_chars`.

    Cases are expected most relevant first, so when the budget runs out the least relevant ones are left off, and the
    closing note says how many.
    """
    lines: list[str] = []
    used = 0
    omitted = 0
    for i, c in enumerate(cases):
        head = f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}"
        line = f"{head}\n  {' '.join(c.summary.split())[:SUMMARY_CHARS]}" if i < detail else head
        if lines and used + len(line) + 1 > max_chars - NOTE_RESERVE:
            omitted = len(cases) - i
            break
        lines.append(line)
        used += len(line) + 1
    plain = max(0, len(cases) - detail)
    if omitted:
        lines.append(f"({plain} more cases without detail, {omitted} not listed here; name one or give its ticket id)")
    elif plain:
        lines.append(f"({plain} more cases listed without detail; name one or give its ticket id)")
    return lines

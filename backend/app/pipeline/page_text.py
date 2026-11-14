"""Plain text for the `<page_facts>` block: one-line values, UTC stamps and the size budget (amendment 2026-10-22).

Every value is normalised the way `data_block` will normalise it (so caps hold after NFKC), collapsed onto one line
and capped. Each rendered line starts with a fixed ASCII anchor (`open case: `, `  msg 07 | `, ...) written by the
server, and stored text (messages, summaries, notes, drafts) only ever follows an anchor on the same line, so it
cannot start a line and fake a fact. `render` keeps the whole text within `FACTS_BUDGET` by dropping whole lines in a
fixed order: older messages first (down to the newest `KEEP_NEWEST`), then visible rows from the bottom, then the
oldest timeline events, then the oldest earlier drafts, then the remaining messages oldest first. Lines without a group
(view, entity headers, case summary, directory facts, open waits) are never dropped. Escaping happens in `data_block`.
"""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.llm.page_blocks import MAX_PAGE_FACTS
from app.llm.render import normalise

FACTS_BUDGET = MAX_PAGE_FACTS  # the whole facts text, after normalisation
MARKER_RESERVE = 300  # room kept for the gap markers and the "left out" line added after fitting
OLD_MESSAGES, VISIBLE, EVENTS, DRAFTS, NEWEST_MESSAGES = range(5)  # drop order: lower groups go first
_GROUP_NAMES = {
    OLD_MESSAGES: "message", NEWEST_MESSAGES: "message", VISIBLE: "visible row", EVENTS: "event", DRAFTS: "draft",
}  # fmt: skip
_NAME_ORDER = ("message", "visible row", "event", "draft")
_LINE_BREAKS = re.compile("[\n\r\v\f\x1c-\x1e\x85  ]")


def one_line(value: str, limit: int) -> str:
    """Normalised, whitespace collapsed to single spaces (no line break of any kind survives), then capped."""
    return " ".join(normalise(value).split())[:limit]


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass(frozen=True)
class Line:
    """One facts line. `group` None: never dropped; else dropped by (group, order). `seq`: a message's position in
    its conversation (1 = first message), 0 for any other line."""

    text: str
    group: int | None = None
    order: int = 0
    seq: int = 0


def fit(lines: Sequence[Line], budget: int) -> list[Line]:
    """Drop droppable lines in (group, order) until the text (lines joined by newlines) fits the budget."""
    size = sum(len(line.text) + 1 for line in lines) - 1
    droppable = sorted((i for i, x in enumerate(lines) if x.group is not None), key=lambda i: _rank(lines[i]))
    gone: set[int] = set()
    for i in droppable:
        if size <= budget:
            break
        gone.add(i)
        size -= len(lines[i].text) + 1
    return [line for i, line in enumerate(lines) if i not in gone]


def _rank(line: Line) -> tuple[int, int]:
    return (line.group if line.group is not None else -1, line.order)


def _with_gaps(lines: Sequence[Line]) -> list[str]:
    """Message lines get a `(N messages not shown)` marker wherever their numbers jump."""
    out: list[str] = []
    last = 0
    for line in lines:
        if line.seq:
            if line.seq > last + 1:
                out.append(f"  ({plural(line.seq - last - 1, 'message')} not shown)")
            last = line.seq
        out.append(line.text)
    return out


def _left_out(before: Sequence[Line], after: Sequence[Line]) -> str:
    counts = Counter(_GROUP_NAMES[x.group] for x in before if x.group is not None)
    counts.subtract(_GROUP_NAMES[x.group] for x in after if x.group is not None)
    parts = [plural(counts[name], name) for name in _NAME_ORDER if counts[name] > 0]
    return f"left out to fit the size limit: {', '.join(parts)}" if parts else ""


def render(lines: Sequence[Line], budget: int = FACTS_BUDGET) -> str:
    """Normalise each line (no line break inside a line), fit the budget, mark gaps and what was left out."""
    clean = [replace(x, text=_LINE_BREAKS.sub(" ", normalise(x.text))) for x in lines]
    kept = fit(clean, budget - MARKER_RESERVE)
    out = _with_gaps(kept)
    if note := _left_out(clean, kept):
        out.append(note)
    return "\n".join(out)

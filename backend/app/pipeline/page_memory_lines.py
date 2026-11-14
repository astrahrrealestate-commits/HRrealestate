"""Lines of the memory pack for the `<page_facts>` block (amendment 2026-10-22), built from `page_memory` facts.

Directory facts and open waits are never dropped; the timeline and earlier drafts are dropped oldest first, and the
conversation's older messages before anything else (`page_text` drop order). Every line starts with a server anchor;
stored text only follows it on the same line.
"""

from collections.abc import Sequence

from app.pipeline.page_memory import (
    MAX_ABOUT,
    MAX_CODE,
    MAX_DRAFTS,
    MAX_EARLIER_DRAFT,
    MAX_EVENTS,
    MAX_LEASES,
    MAX_MESSAGE,
    MAX_MESSAGES,
    MAX_NAME,
    MAX_NOTE,
    MAX_WAITS,
    CaseMemory,
    Conversation,
    MemoryMessage,
)
from app.pipeline.page_text import DRAFTS, EVENTS, NEWEST_MESSAGES, OLD_MESSAGES, Line, plural

KEEP_NEWEST = 6  # the budget drops other sections before these newest messages


def _directory_lines(memory: CaseMemory) -> list[Line]:
    lines: list[Line] = []
    if p := memory.person:
        lines.append(Line(f"  person: {p.name[:MAX_NAME]} | {p.kind[:MAX_CODE]}"))
    for x in memory.leases[:MAX_LEASES]:
        validity = "current" if x.end is None else f"not current since {x.end[:MAX_CODE]}"
        head = f"  lease: {x.role[:MAX_CODE]} | unit {x.unit[:MAX_NAME]}"
        lines.append(Line(f"{head} | valid from {x.start[:MAX_CODE]} | {validity}"))
    return lines


def _wait_lines(memory: CaseMemory) -> list[Line]:
    waits = memory.waits[:MAX_WAITS]
    if not waits:
        return [Line("  open waits: none")]
    return [
        Line(
            f"  open wait: {w.who[:MAX_NAME]} | {w.about[:MAX_ABOUT]} | expected by {w.expected_by} | chased {w.chased}"
        )
        for w in waits
    ]


def memory_lines(memory: CaseMemory) -> list[Line]:
    """Directory facts and open waits (never dropped), then the timeline and earlier drafts (dropped oldest first).
    Every field is capped here too, whatever the caller built."""
    lines = [*_directory_lines(memory), *_wait_lines(memory)]
    for i, e in enumerate(memory.events[-MAX_EVENTS:]):
        head = f"  event: {e.at[:MAX_CODE]} | {e.kind[:MAX_CODE]} | {e.change[: 2 * MAX_CODE]} | {e.actor[:MAX_CODE]}"
        lines.append(Line(f"{head} | {e.note[:MAX_NOTE]}", EVENTS, i))
    for i, d in enumerate(memory.drafts[-MAX_DRAFTS:]):
        head = f"  earlier draft: {d.action_type[:MAX_CODE]} | {d.status[:MAX_CODE]} | draft_version {d.draft_version}"
        tail = f"owner decision {d.decision[:MAX_CODE]} | edits {d.edits} | {d.text[:MAX_EARLIER_DRAFT]}"
        lines.append(Line(f"{head} | {tail}", DRAFTS, i))
    return lines


def conversation_lines(conversation: Conversation) -> list[Line]:
    """A header, then one line per message, oldest first; the newest KEEP_NEWEST are dropped last."""
    messages: Sequence[MemoryMessage] = conversation.messages[-MAX_MESSAGES:]
    width = max(2, len(str(conversation.total)))
    header = f"conversation ({conversation.source}, {plural(conversation.total, 'message')}, oldest first, times UTC):"
    newest = {m.seq for m in messages[-KEEP_NEWEST:]}
    lines = [Line(header)]
    for m in messages:
        head = f"  msg {m.seq:0{width}d} | {m.direction[:MAX_CODE]} | {m.channel[:MAX_CODE]} | {m.at[:MAX_CODE]}"
        group = NEWEST_MESSAGES if m.seq in newest else OLD_MESSAGES
        lines.append(Line(f"{head} | {m.text[:MAX_MESSAGE] or '(no text)'}", group, m.seq, m.seq))
    return lines

"""The page blocks of a Super Agent prompt (spec amendment 2026-10-16), shared by the concierge and owner_qa.

`<page_facts>` is authoritative server text (resolved company-scoped); `<page_snapshot>` holds the browser's filters
line and page text, both UNVERIFIED. Both are escaped data blocks, never instructions (CLAUDE.md invariant 6). Only the
snapshot is capped at `MAX_SNAPSHOT`; the filters line has its own cap, so it can never cut the snapshot's end.
`<page_facts>` alone has the larger cap `MAX_PAGE_FACTS` (amendment 2026-10-22): the memory pack of an open thread or
case is kept at most that long after normalisation (`app.pipeline.page_text.FACTS_BUDGET`), so the block never cuts it;
every other block keeps `MAX_BODY_CHARS`, and escaping still runs after truncation. When the facts carry a memory pack
(a conversation or case memory: server-anchored lines that tenant text cannot start), the snapshot cap drops to
`MAX_SNAPSHOT_WITH_MEMORY`: the facts already hold the thread, so the unverified copy of the screen gets less room.
"""

import re
from dataclasses import dataclass

from app.llm.render import data_block

MAX_SNAPSHOT = 6000  # the page snapshot (the request contract enforces the same limit)
MAX_FILTERS_LINE = 1700  # `filters: ` plus 10 pairs of 40 + 120 characters; with the snapshot under MAX_BODY_CHARS
MAX_PAGE_FACTS = 12000  # the `<page_facts>` block only: the memory pack budget (render.MAX_BODY_CHARS is 8000)
MAX_SNAPSHOT_WITH_MEMORY = 3000  # the snapshot cap when the facts carry a memory pack
_MEMORY_PACK = re.compile(r"^(?:conversation \(|  open waits?: )", re.M)  # page_memory_lines anchors


@dataclass(frozen=True)
class PagePrompt:
    """What a model sees of the open page: server facts text, the unverified snapshot and the unverified filters."""

    facts: str = ""
    snapshot: str = ""
    filters: str = ""  # one `filters: k=v; ...` line, or empty

    @property
    def present(self) -> bool:
        return bool(self.facts.strip() or self.snapshot.strip() or self.filters.strip())


NO_PAGE = PagePrompt()


def snapshot_cap(page_facts_text: str) -> int:
    """`MAX_SNAPSHOT_WITH_MEMORY` when the facts carry a memory pack (a conversation header or the case's open-waits
    line at the start of a line), else `MAX_SNAPSHOT`."""
    return MAX_SNAPSHOT_WITH_MEMORY if _MEMORY_PACK.search(page_facts_text) else MAX_SNAPSHOT


def page_blocks(page_facts_text: str, snapshot: str, filters: str = "") -> list[str]:
    """Server facts (authoritative) and the browser's filters + snapshot (unverified). An absent page adds nothing,
    so a page-less prompt is unchanged."""
    blocks = [data_block("page_facts", page_facts_text, MAX_PAGE_FACTS)] if page_facts_text.strip() else []
    capped = snapshot[: snapshot_cap(page_facts_text)]
    unverified = [part for part in (filters.strip()[:MAX_FILTERS_LINE], capped) if part.strip()]
    if unverified:
        blocks.append(data_block("page_snapshot", "\n".join(unverified)))
    return blocks

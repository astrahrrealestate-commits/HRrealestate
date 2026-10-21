"""The page blocks of a Super Agent prompt (spec amendment 2026-10-16), shared by the concierge and owner_qa.

`<page_facts>` is authoritative server text (resolved company-scoped); `<page_snapshot>` holds the browser's filters
line and page text, both UNVERIFIED. Both are escaped data blocks, never instructions (CLAUDE.md invariant 6). Only the
snapshot is capped at `MAX_SNAPSHOT`; the filters line has its own cap, so it can never cut the snapshot's end.
"""

from dataclasses import dataclass

from app.llm.render import data_block

MAX_SNAPSHOT = 6000  # the page snapshot (the request contract enforces the same limit)
MAX_FILTERS_LINE = 1700  # `filters: ` plus 10 pairs of 40 + 120 characters; with the snapshot under MAX_BODY_CHARS


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


def page_blocks(page_facts_text: str, snapshot: str, filters: str = "") -> list[str]:
    """Server facts (authoritative) and the browser's filters + snapshot (unverified). An absent page adds nothing,
    so a page-less prompt is unchanged."""
    blocks = [data_block("page_facts", page_facts_text)] if page_facts_text.strip() else []
    unverified = [part for part in (filters.strip()[:MAX_FILTERS_LINE], snapshot[:MAX_SNAPSHOT]) if part.strip()]
    if unverified:
        blocks.append(data_block("page_snapshot", "\n".join(unverified)))
    return blocks

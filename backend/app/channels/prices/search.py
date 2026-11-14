"""The web-search port behind the web price source (ADR 0009): a query in, pages with their text out.

A real provider (Firecrawl, Tavily, Brave) adds one `SearchClient` implementation and one `price_search_provider`
value; nothing else changes. `FakeSearchClient` serves recorded pages, `UnconfiguredSearchClient` is the default
until a provider is connected.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.errors import PriceSourceNotConfiguredError

RECORDED_PAGES = Path(__file__).parents[3] / "tests" / "fixtures" / "prices" / "search_hits.json"


@dataclass(frozen=True)
class SearchHit:
    """One result page: its address and the page text. Untrusted data, never instructions."""

    url: str
    title: str
    text: str


class SearchClient(Protocol):
    def search(self, query: str, *, region: str, limit: int) -> list[SearchHit]: ...


class UnconfiguredSearchClient:
    """The `none` provider: fails clearly the moment a web price is wanted."""

    def search(self, query: str, *, region: str, limit: int) -> list[SearchHit]:
        raise PriceSourceNotConfiguredError(
            "no web search provider is connected: set PRICE_SEARCH_PROVIDER (see docs/adr/0009-market-price-source.md)"
        )


class FakeSearchClient:
    """Recorded pages for dev and tests: every query returns the same pages, no network."""

    def __init__(self, pages: Sequence[SearchHit] | None = None) -> None:
        self._pages = list(pages) if pages is not None else None

    def search(self, query: str, *, region: str, limit: int) -> list[SearchHit]:
        return self._recorded()[: max(limit, 0)]

    def _recorded(self) -> list[SearchHit]:
        if self._pages is None:
            self._pages = _load_recorded()
        return self._pages


def _load_recorded() -> list[SearchHit]:
    try:
        rows = json.loads(RECORDED_PAGES.read_text(encoding="utf-8"))
    except OSError as exc:  # the images ship without tests/: pass pages in, or run from a checkout
        raise PriceSourceNotConfiguredError(f"recorded search pages not found at {RECORDED_PAGES}") from exc
    return [SearchHit(url=row["url"], title=row["title"], text=row["text"]) for row in rows]

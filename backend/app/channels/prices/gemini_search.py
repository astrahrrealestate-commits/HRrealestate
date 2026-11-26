"""Web search on the Gemini key (ADR 0009): Google Search grounding names the sources, `page_fetch` reads the pages.

Grounding returns Google redirect links and a site name, not the page. Each source is fetched (a few at a time) and the
hit carries the address the page was really read from and its own text, so prices and findings stay checkable. A source
that cannot be fetched is dropped. `allowed_domains` limits both the query (`site:`) and the pages (final host).
"""

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

from sqlalchemy import Engine

from app.channels.prices.page_fetch import HttpPageFetcher, PageFetcher, PageFetchError
from app.channels.prices.search import SearchHit
from app.core.errors import PriceSourceNotConfiguredError
from app.core.logging import get_logger
from app.core.settings import Settings
from app.llm.runtime import model_name_for
from app.llm.web_search import NAME, WebSource, grounded_search

log = get_logger(__name__)
FETCH_WORKERS = 4  # pages read at once: a page may take 10 seconds, the research step has 60


class GeminiSearchClient:
    def __init__(
        self,
        settings: Settings,
        *,
        engine: Engine | None = None,
        company_id: UUID | None = None,
        allowed_domains: Sequence[str] = (),
        fetcher: PageFetcher | None = None,
    ) -> None:
        if not model_name_for(settings, NAME).startswith("google-gla:"):
            raise PriceSourceNotConfiguredError("PRICE_SEARCH_PROVIDER=gemini needs a google-gla: LLM_MODEL")
        self._settings = settings
        self._engine = engine
        self._company_id = company_id
        self._domains = tuple(d.lower() for d in allowed_domains)
        self._fetcher = fetcher or HttpPageFetcher()

    def search(self, query: str, *, region: str, limit: int) -> list[SearchHit]:
        if limit <= 0:
            return []
        sites = " OR ".join(f"site:{d}" for d in self._domains)
        sources = grounded_search(
            self._settings, f"{query} ({sites})" if sites else query, region,
            engine=self._engine, company_id=self._company_id,
        )  # fmt: skip
        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            read = list(pool.map(self._read, sources[:limit]))
        hits: dict[str, SearchHit] = {}  # two redirect links can lead to one page
        for hit in read:
            if hit is not None:
                hits.setdefault(hit.url, hit)
        return list(hits.values())

    def _read(self, source: WebSource) -> SearchHit | None:
        try:
            page = self._fetcher.fetch(source.url, allowed_domains=self._domains)
        except PageFetchError as exc:
            log.info("prices.gemini_search.source_dropped", site=source.title[:80], reason=str(exc)[:120])
            return None
        if not page.text.strip():
            return None
        return SearchHit(url=page.url, title=page.title or source.title, text=page.text)

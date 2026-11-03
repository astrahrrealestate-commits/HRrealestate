"""Web price source: search pages for an item, let the injected extractor read each page, keep only what checks out.

The extractor is an LLM call wired in `app.finance.sources`; its output is untrusted. Per page it must pass:
- the observation's URL is the search hit's own (never anything the model said), and is http(s);
- the evidence snippet occurs in the page text (whitespace, case and Unicode form ignored) and carries the amount;
- the amount is in EUR, and the unit is the wanted unit (after `normalise_unit`).
The first price that passes is the page's one observation; VAT unknown counts as included (a consumer price).
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

from app.channels.prices.ports import PriceObservation
from app.channels.prices.search import SearchClient, SearchHit
from app.contracts import ExtractedPrice, ExtractedPrices
from app.core.logging import get_logger
from app.core.property_terms import normalise_unit

log = get_logger(__name__)

REGION = "NL"
DEFAULT_MAX_HITS = 8
CURRENCY = "EUR"
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")

Extractor = Callable[[SearchHit, str, str], ExtractedPrices]


def _squash(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _host(url: str) -> str | None:
    """The page's host without a leading `www.`, or None unless the URL is http(s) with a host."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    return host if parts.scheme in ("http", "https") and host else None


def _carries_amount(evidence: str, amount: Decimal) -> bool:
    whole = str(int(amount))
    return re.search(rf"(?<!\d){whole}(?!\d)", _THOUSANDS.sub("", evidence)) is not None


class WebPriceSource:
    def __init__(
        self,
        search: SearchClient,
        extract: Extractor,
        allowed_domains: Sequence[str] = (),
        max_hits: int = DEFAULT_MAX_HITS,
    ) -> None:
        self.search = search
        self.extract = extract
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.max_hits = max_hits

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        observations: list[PriceObservation] = []
        for hit in self._hits(item_key):
            observed = self._observe(hit, item_key, unit, as_of)
            if observed is not None:
                observations.append(observed)
        return observations

    def _hits(self, item_key: str) -> list[SearchHit]:
        """Dutch then English results, each URL once, at most `max_hits` pages in all."""
        name = item_key.replace("_", " ")
        queries = (f"{name} prijs Nederland", f"{name} price Netherlands")
        hits: dict[str, SearchHit] = {}
        for i, query in enumerate(queries):
            room = -(-self.max_hits // 2) if i == 0 else self.max_hits - len(hits)
            if room > 0:
                for hit in self.search.search(query, region=REGION, limit=room):
                    hits.setdefault(hit.url, hit)
        return list(hits.values())[: self.max_hits]

    def _allowed(self, host: str) -> bool:
        return not self.allowed_domains or any(host == d or host.endswith("." + d) for d in self.allowed_domains)

    def _observe(self, hit: SearchHit, item_key: str, unit: str, as_of: date) -> PriceObservation | None:
        host = _host(hit.url)
        if host is None or not self._allowed(host):
            log.info("prices.web.page_skipped", host=host)
            return None
        try:
            found = self.extract(hit, item_key, unit)
        except Exception as exc:  # one unreadable page (model, budget, parse) must not lose the other pages
            log.warning("prices.web.extract_failed", host=host, error=type(exc).__name__)
            return None
        page = _squash(hit.text)
        for price in found.prices:
            if self._valid(price, unit, page):
                return PriceObservation(
                    amount=price.amount.amount,
                    unit=unit,
                    vat_included=price.vat_included is not False,
                    source=host,
                    url=hit.url,
                    observed_on=as_of,
                )
        return None

    @staticmethod
    def _valid(price: ExtractedPrice, unit: str, page: str) -> bool:
        return (
            price.amount.currency == CURRENCY
            and normalise_unit(price.unit) == normalise_unit(unit)
            and _squash(price.evidence) in page
            and _carries_amount(price.evidence, price.amount.amount)
        )

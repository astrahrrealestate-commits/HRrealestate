"""Compose the configured price sources for one quote review."""

from collections.abc import Callable, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.channels.prices.ports import PriceObservation, PriceSource
from app.channels.prices.search import SearchHit
from app.channels.prices.web import Extractor, WebPriceSource
from app.channels.registry import search_client
from app.contracts import ExtractedPrices
from app.core.errors import PriceSourceNotConfiguredError
from app.core.settings import Settings
from app.finance.competitors import CompetitorRatesSource
from app.llm.agents.price_extractor import PRICE_EXTRACTOR, price_extractor_prompt
from app.llm.calls import CallContext, run_agent

PURPOSE = "price_extractor"


class CompositePriceSource:
    def __init__(self, sources: Sequence[PriceSource]) -> None:
        self.sources = list(sources)

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        return [obs for source in self.sources for obs in source.lookup(item_key, unit, as_of)]


def llm_price_extractor(engine: Engine, settings: Settings, company_id: UUID) -> Extractor:
    """The page reader for the web source: one `price_extractor` call per page, recorded in `model_calls`."""

    def extract(hit: SearchHit, item_key: str, unit: str) -> ExtractedPrices:
        prompt = price_extractor_prompt(item_key, unit, hit.title, hit.text)
        return run_agent(engine, settings, PRICE_EXTRACTOR, prompt, CallContext(company_id, PURPOSE)).output

    return extract


def _web_source(settings: Settings, engine: Engine | None, company_id: UUID) -> WebPriceSource:
    if settings.price_search_provider == "none":
        raise PriceSourceNotConfiguredError(
            "price_source 'web' needs a search provider: set PRICE_SEARCH_PROVIDER (ADR 0009)"
        )
    if engine is None:
        raise PriceSourceNotConfiguredError("price_source 'web' needs a database engine for the page extractor")
    return WebPriceSource(
        search_client(settings),
        llm_price_extractor(engine, settings, company_id),
        allowed_domains=settings.price_allowed_domains,
    )


def build_price_source(
    settings: Settings,
    session_factory: Callable[[], Session],
    company_id: UUID,
    exclude_person_id: UUID | None,
    engine: Engine | None = None,
) -> PriceSource:
    """The configured sources; competitor rate cards (minus `exclude_person_id`) are always included. `engine` is
    only needed for `web` (the page extractor records its model calls)."""
    competitors = CompetitorRatesSource(session_factory, company_id, exclude_person_id)
    match settings.price_source:
        case "fake":
            return CompositePriceSource([FakePriceSource(), competitors])
        case "competitors":
            return CompositePriceSource([competitors])
        case "web":
            return CompositePriceSource([_web_source(settings, engine, company_id), competitors])

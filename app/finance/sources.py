"""Compose the configured price sources for one quote review."""

from collections.abc import Callable, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.channels.prices.fake import FakePriceSource
from app.channels.prices.ports import PriceObservation, PriceSource
from app.core.errors import PriceSourceNotConfiguredError
from app.core.settings import Settings
from app.finance.competitors import CompetitorRatesSource


class CompositePriceSource:
    def __init__(self, sources: Sequence[PriceSource]) -> None:
        self.sources = list(sources)

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        return [obs for source in self.sources for obs in source.lookup(item_key, unit, as_of)]


def build_price_source(
    settings: Settings,
    session_factory: Callable[[], Session],
    company_id: UUID,
    exclude_person_id: UUID | None,
) -> PriceSource:
    competitors = CompetitorRatesSource(session_factory, company_id, exclude_person_id)
    match settings.price_source:
        case "fake":
            return CompositePriceSource([FakePriceSource(), competitors])
        case "competitors":
            return CompositePriceSource([competitors])
        case "web":
            raise PriceSourceNotConfiguredError("price_source 'web' has no adapter configured yet")

"""The price-source port: observed market prices for an item, each traceable to its source."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

URL_OPTIONAL_SOURCES = ("owner",)
URL_OPTIONAL_PREFIX = "competitor:"


@dataclass(frozen=True)
class PriceObservation:
    """One observed price. Every observation names its source; only the owner's own numbers and competitor rate
    cards (rows in our DB) may lack a URL, everything else must be checkable on the web."""

    amount: Decimal
    unit: str
    vat_included: bool
    source: str
    url: str | None
    observed_on: date

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"amount must be positive, got {self.amount}")
        if not self.source.strip():
            raise ValueError("source must not be blank")
        if self.url is None and not self._url_optional():
            raise ValueError(f"url is required for source {self.source!r}")
        if self.url is not None and not self.url.startswith(("http://", "https://")):
            raise ValueError(f"url must be http(s), got {self.url!r}")

    def _url_optional(self) -> bool:
        return self.source in URL_OPTIONAL_SOURCES or self.source.startswith(URL_OPTIONAL_PREFIX)


class PriceSource(Protocol):
    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]: ...

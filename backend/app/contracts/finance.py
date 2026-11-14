"""Quote Checker contracts (M11): what the quote reader extracts, the job it is checked against, and the verdict
vocabularies. `ExtractedQuote`, `JobItems` and `ExtractedPrices` are LLM `output_type`s, so they follow the
strict-schema rules in `common.py` (no defaults, no length keywords on strings).
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, Field, WithJsonSchema

from app.contracts.common import Contract, Money, NonBlankStr, max_len

MAX_QUOTE_LINES = 40
MAX_JOB_ITEMS = 10
MAX_EXTRACTED_PRICES = 10
MAX_EVIDENCE_CHARS = 300
MAX_QUANTITY = Decimal(100000)

Quantity = Annotated[
    Decimal,
    Field(gt=0, le=MAX_QUANTITY, max_digits=9, decimal_places=3),
    WithJsonSchema({"type": "string", "pattern": r"^[0-9]{1,6}(\.[0-9]{1,3})?$"}),
]


def _require_positive(value: Money) -> Money:
    if value.amount <= 0:
        raise ValueError("must be greater than zero (credit and discount lines are not supported)")
    return value


PositiveMoney = Annotated[Money, AfterValidator(_require_positive)]


class Verdict(StrEnum):
    ok = "ok"
    needs_check = "needs_check"
    above_market = "above_market"
    well_above_market = "well_above_market"
    above_agreed = "above_agreed"


class LineStatus(StrEnum):
    ok = "ok"
    above_agreed = "above_agreed"
    above_market = "above_market"
    well_above_market = "well_above_market"
    suspiciously_low = "suspiciously_low"
    no_reference = "no_reference"
    currency_mismatch = "currency_mismatch"


class PriceBasis(StrEnum):
    """Where a reference price came from (`fake` = the offline test source)."""

    web = "web"
    competitor = "competitor"
    owner = "owner"
    fake = "fake"


class SnapshotBasis(StrEnum):
    decision_day = "decision_day"
    estimate_current_prices = "estimate_current_prices"


class QuoteLine(Contract):
    description: Annotated[NonBlankStr, max_len(200)]
    quantity: Quantity
    unit: Annotated[str, max_len(30)]
    unit_price: PositiveMoney | None
    amount: PositiveMoney
    vat_included: bool | None


class ExtractedQuote(Contract):
    """Output of the quote_reader agent. `is_quote` is false for a document that is not a quote at all."""

    lines: Annotated[list[QuoteLine], Field(max_length=MAX_QUOTE_LINES)]
    total: PositiveMoney | None
    quote_date: date | None
    work_date: date | None
    vat_included: bool | None
    is_quote: bool


class JobItem(Contract):
    description: Annotated[NonBlankStr, max_len(200)]
    quantity: Quantity
    unit: Annotated[str, max_len(30)]


class JobItems(Contract):
    """What the job is, in priceable lines, for a cost estimate or a quote check."""

    items: Annotated[list[JobItem], Field(max_length=MAX_JOB_ITEMS)]


class ExtractedPrice(Contract):
    """One price a web page states for the wanted service. `amount` carries the page's currency (the source keeps
    EUR only); `evidence` is a short snippet copied from the page, checked against it before the price is used."""

    amount: PositiveMoney
    unit: Annotated[str, max_len(30)]
    vat_included: bool | None
    evidence: Annotated[NonBlankStr, max_len(MAX_EVIDENCE_CHARS)]


class ExtractedPrices(Contract):
    """Output of the price_extractor agent for one page; empty when the page states no matching price."""

    prices: Annotated[list[ExtractedPrice], Field(max_length=MAX_EXTRACTED_PRICES)]

"""Inputs and outputs of the pure quote review (`app.finance.review`). Pure: no I/O layers (import-linter contract).

All prices on the reference side (rate card, market stats) are excl. VAT, per `Reference.unit`, in
`Reference.currency`. Quote lines keep what the quote states; the review normalises them.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.contracts.finance import LineStatus, SnapshotBasis, Verdict
from app.finance.stats import MarketStats

REFERENCE_CURRENCY = "EUR"

# Quote verdict = the most severe line verdict under this order (see app.finance.review).
SEVERITY: Mapping[Verdict, int] = {
    Verdict.ok: 0,
    Verdict.needs_check: 1,
    Verdict.above_market: 2,
    Verdict.above_agreed: 3,
    Verdict.well_above_market: 4,
}

STATUS_VERDICT: Mapping[LineStatus, Verdict] = {
    LineStatus.ok: Verdict.ok,
    LineStatus.above_agreed: Verdict.above_agreed,
    LineStatus.above_market: Verdict.above_market,
    LineStatus.well_above_market: Verdict.well_above_market,
    LineStatus.suspiciously_low: Verdict.needs_check,
    LineStatus.no_reference: Verdict.needs_check,
    LineStatus.currency_mismatch: Verdict.needs_check,
}


class ReferenceKind(StrEnum):
    rate_card = "rate_card"
    market = "market"


@dataclass(frozen=True)
class Thresholds:
    """Percentages are "over the reference" (5 = 5 %); `low_ratio` and `vat_rate` are fractions."""

    ok_pct: Decimal
    above_market_pct: Decimal
    well_above_pct: Decimal
    low_ratio: Decimal
    late_days: int
    min_samples: int
    vat_rate: Decimal

    def __post_init__(self) -> None:
        if not Decimal(0) < self.low_ratio < Decimal(1):
            raise ValueError("low_ratio must be between 0 and 1 (exclusive)")
        if not Decimal(0) <= self.ok_pct < self.above_market_pct < self.well_above_pct:
            raise ValueError("thresholds must satisfy 0 <= ok_pct < above_market_pct < well_above_pct")
        if self.late_days < 1 or self.min_samples < 1:
            raise ValueError("late_days and min_samples must be at least 1")
        if not Decimal(0) <= self.vat_rate < Decimal(1):
            raise ValueError("vat_rate must be a fraction in [0, 1)")


@dataclass(frozen=True)
class Reference:
    """What one job item should cost per `unit`: the vendor's rate card on the decision day, the market snapshot
    then, and the market now (for drift only)."""

    unit: str
    rate_card: Decimal | None = None
    market: MarketStats | None = None
    market_now: MarketStats | None = None
    currency: str = REFERENCE_CURRENCY

    def __post_init__(self) -> None:
        if self.rate_card is not None and self.rate_card <= 0:
            raise ValueError("a rate card amount must be positive")


@dataclass(frozen=True)
class ReviewLine:
    """One quote line. `vat_included` / `currency` of None fall back to the quote-level values."""

    description: str
    quantity: Decimal
    unit: str
    amount: Decimal
    unit_price: Decimal | None = None
    vat_included: bool | None = None
    item_key: str | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("a quote line quantity must be positive")
        if self.unit_price is not None and self.unit_price <= 0:
            raise ValueError("a quote line unit price must be positive")


@dataclass(frozen=True)
class ReviewInput:
    """`lump_sum` = the quote states one price for the whole job; a single line on a multi-item job counts too."""

    lines: tuple[ReviewLine, ...]
    currency: str
    quote_date: date
    decision_date: date
    references: Mapping[str, Reference]
    snapshot_basis: SnapshotBasis
    vat_included: bool | None = None
    lump_sum: bool = False


@dataclass(frozen=True)
class LineResult:
    """`reference` is the per-unit amount compared against (`reference_kind` says which); `vs_*_pct` are shown for
    both references when comparable. `low_confidence` = a flag (VAT unknown, thin market, lump sum) holds the line at
    `needs_check` in the quote verdict, whatever its `status`."""

    item_key: str | None
    status: LineStatus
    reference: Decimal | None
    reference_kind: ReferenceKind | None
    unit_price_excl_vat: Decimal | None
    vs_rate_card_pct: Decimal | None
    vs_market_pct: Decimal | None
    overcharge: Decimal | None
    vat_unknown: bool
    vs_reference_pct_if_vat_included: Decimal | None
    low_confidence: bool


@dataclass(frozen=True)
class ReviewResult:
    lines: list[LineResult]
    verdict: Verdict
    worst_line_index: int | None
    overcharge_total: Decimal
    late_days: int
    late_flag: bool
    drift_pct: dict[str, Decimal | None]
    low_confidence: bool

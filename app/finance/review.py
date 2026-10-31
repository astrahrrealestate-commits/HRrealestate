"""Quote review: compare each quote line with its job item's reference and decide a verdict. Pure: no I/O layers
(import-linter contract), no clock, no model. The model only reads quotes into fields; every number here is code.

Per line, per UNIT, against ONE reference: the rate card valid on the decision day if any, else the market average
(both excl. VAT). Rate card: up to `ok_pct` over → `ok`, more → `above_agreed`. Market: up to `above_market_pct` over
→ `ok` (market averages are noisy), up to `well_above_pct` → `above_market`, more → `well_above_market`. Under
`low_ratio` × reference → `suspiciously_low` (scope risk). No item reference, a different unit (per hour vs per job)
or no rate card and no market → `no_reference`; a currency other than the reference's → `currency_mismatch`, no maths.

VAT: the line's `vat_included`, else the quote's. Still unknown → the stated price is compared as if excl. VAT, the
incl.-VAT reading is shown beside it, and the line is flagged.

Verdict = the MOST SEVERE line verdict (ok < needs_check < above_market < above_agreed < well_above_market), not
weighted by amount: weighting would let a price rise improve the verdict. Amount only picks `worst_line_index`.
Flags hold a line at `needs_check` (never `ok`): VAT unknown, a thin (`low_confidence`) market reference, a lump-sum
quote. A flagged line or a snapshot estimated from current prices caps the verdict at `needs_check` and sets
`low_confidence`. Overcharge per comparable line = max(0, (unit price − reference) × quantity).
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

from app.contracts.finance import LineStatus, SnapshotBasis, Verdict
from app.finance.review_types import (
    SEVERITY,
    STATUS_VERDICT,
    LineResult,
    Reference,
    ReferenceKind,
    ReviewInput,
    ReviewLine,
    ReviewResult,
    Thresholds,
)

CENT = Decimal("0.01")
HUNDRED = Decimal(100)
ZERO = Decimal("0.00")


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _strip_vat(amount: Decimal, rate: Decimal) -> Decimal:
    return _cents(amount / (1 + rate))


def to_excl_vat(amount: Decimal, vat_included: bool | None, rate: Decimal) -> Decimal | None:
    """None when it is unknown whether `amount` includes VAT."""
    if vat_included is None:
        return None
    return _strip_vat(amount, rate) if vat_included else amount


def _pct(price: Decimal, reference: Decimal) -> Decimal:
    return _cents((price - reference) / reference * HUNDRED)


def _unit_prices(line: ReviewLine, quote_vat: bool | None, rate: Decimal) -> tuple[Decimal, Decimal | None]:
    """(per-unit price excl. VAT, per-unit price if the stated one included VAT — only when VAT is unknown)."""
    stated = line.unit_price if line.unit_price is not None else line.amount
    per = Decimal(1) if line.unit_price is not None else line.quantity
    vat = line.vat_included if line.vat_included is not None else quote_vat
    excl = to_excl_vat(stated, vat, rate)
    if excl is not None:
        return excl / per, None
    return stated / per, _strip_vat(stated, rate) / per


def _pick(ref: Reference) -> tuple[ReferenceKind, Decimal] | None:
    if ref.rate_card is not None:
        return ReferenceKind.rate_card, ref.rate_card
    if ref.market is not None:
        return ReferenceKind.market, ref.market.avg
    return None


def _status(price: Decimal, reference: Decimal, kind: ReferenceKind, t: Thresholds) -> LineStatus:
    if price < reference * t.low_ratio:
        return LineStatus.suspiciously_low
    pct = _pct(price, reference)
    if kind is ReferenceKind.rate_card:
        return LineStatus.ok if pct <= t.ok_pct else LineStatus.above_agreed
    if pct <= t.above_market_pct:
        return LineStatus.ok
    return LineStatus.above_market if pct <= t.well_above_pct else LineStatus.well_above_market


def _uncompared(line: ReviewLine, status: LineStatus) -> LineResult:
    return LineResult(
        item_key=line.item_key,
        status=status,
        reference=None,
        reference_kind=None,
        unit_price_excl_vat=None,
        vs_rate_card_pct=None,
        vs_market_pct=None,
        overcharge=None,
        vat_unknown=False,
        vs_reference_pct_if_vat_included=None,
        low_confidence=False,
    )


def _blocker(line: ReviewLine, quote: ReviewInput, ref: Reference | None) -> LineStatus | None:
    if ref is None:
        return LineStatus.no_reference
    if (line.currency or quote.currency) != ref.currency:
        return LineStatus.currency_mismatch
    if line.unit.strip().casefold() != ref.unit.strip().casefold():
        return LineStatus.no_reference
    return None


def _review_line(line: ReviewLine, quote: ReviewInput, t: Thresholds, *, lump_sum: bool) -> LineResult:
    ref = quote.references.get(line.item_key) if line.item_key is not None else None
    blocker = _blocker(line, quote, ref)
    picked = _pick(ref) if ref is not None else None
    if ref is None or picked is None or blocker is not None:
        return _uncompared(line, blocker or LineStatus.no_reference)
    kind, reference = picked
    price, if_incl = _unit_prices(line, quote.vat_included, t.vat_rate)
    thin = kind is ReferenceKind.market and ref.market is not None and ref.market.low_confidence
    return LineResult(
        item_key=line.item_key,
        status=_status(price, reference, kind, t),
        reference=reference,
        reference_kind=kind,
        unit_price_excl_vat=_cents(price),
        vs_rate_card_pct=_pct(price, ref.rate_card) if ref.rate_card is not None else None,
        vs_market_pct=_pct(price, ref.market.avg) if ref.market is not None else None,
        overcharge=_cents(max(Decimal(0), (price - reference) * line.quantity)),
        vat_unknown=if_incl is not None,
        vs_reference_pct_if_vat_included=_pct(if_incl, reference) if if_incl is not None else None,
        low_confidence=if_incl is not None or thin or lump_sum,
    )


def _held(result: LineResult) -> Verdict:
    return Verdict.needs_check if result.low_confidence else STATUS_VERDICT[result.status]


def _verdict(results: Sequence[LineResult], capped: bool) -> Verdict:
    if not results:
        return Verdict.needs_check
    worst = max((_held(r) for r in results), key=SEVERITY.__getitem__)
    if capped and SEVERITY[worst] > SEVERITY[Verdict.needs_check]:
        return Verdict.needs_check
    return worst


def worst_line_index(quote: ReviewInput, results: Sequence[LineResult]) -> int | None:
    """The line with the most severe finding (status, before caps); ties go to the larger amount, then the first."""
    if not results:
        return None
    ranked = range(len(results))
    return max(ranked, key=lambda i: (SEVERITY[STATUS_VERDICT[results[i].status]], quote.lines[i].amount, -i))


def _drift(ref: Reference) -> Decimal | None:
    if ref.market is None or ref.market_now is None:
        return None
    return _pct(ref.market_now.avg, ref.market.avg)


def review_quote(quote: ReviewInput, thresholds: Thresholds) -> ReviewResult:
    lump_sum = quote.lump_sum or (len(quote.lines) == 1 and len(quote.references) > 1)
    results = [_review_line(line, quote, thresholds, lump_sum=lump_sum) for line in quote.lines]
    estimate = quote.snapshot_basis is SnapshotBasis.estimate_current_prices
    low_confidence = estimate or any(r.low_confidence for r in results)
    late_days = max(0, (quote.quote_date - quote.decision_date).days)
    return ReviewResult(
        lines=results,
        verdict=_verdict(results, low_confidence),
        worst_line_index=worst_line_index(quote, results),
        overcharge_total=_cents(sum((r.overcharge for r in results if r.overcharge is not None), ZERO)),
        late_days=late_days,
        late_flag=late_days >= thresholds.late_days,
        drift_pct={key: _drift(ref) for key, ref in quote.references.items()},
        low_confidence=low_confidence,
    )

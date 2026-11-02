"""The quote review as the owner reads it: the `quote_reviews.report` and the `quote_review` feed card payload (one
shape, reused by the finance API). Pure. JSON only: Decimals as strings (never floats), dates ISO, ids as strings.

Honesty fields: `snapshot_basis` (an estimate from current prices is labelled), `low_confidence`, `lump_sum`,
`skipped_lines`, per line `reference_as_of` (`decision_day` | `estimate`; null = no reference) and `vat_unknown`
with the incl.-VAT reading beside it, and whether `overcharge_total` assumed excl. VAT for lines whose VAT was
unknown. Every market figure carries its sources (each with a name).
"""

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.finance.quote_lines import QuoteFacts, ReviewOutcome
from app.finance.references import LUMP_SUM_KEY, ItemReference, ReferencePlan
from app.finance.repo_quotes import NewQuoteLine
from app.finance.review_types import LineResult
from app.finance.stats import MarketStats

_SOURCE_FIELDS = ("name", "url", "price", "observed_on", "item_key")


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _quantity(value: Decimal) -> str:
    """Fixed point without trailing zeros: 10 → "10" (never "1E+1"), 2.500 → "2.5"."""
    return f"{value.normalize():f}"


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _id(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _stats(stats: MarketStats | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    return {
        "low": _dec(stats.low), "avg": _dec(stats.avg), "high": _dec(stats.high), "n": stats.n,
        "low_confidence": stats.low_confidence,
    }  # fmt: skip


def _market(item: ItemReference | None) -> dict[str, Any] | None:
    stats = _stats(item.reference.market) if item is not None else None
    if item is None or stats is None:
        return None
    sources = [{k: entry[k] for k in _SOURCE_FIELDS if k in entry} for entry in item.sources]
    return {**stats, "sources": sources}


def _reference(result: LineResult, item: ItemReference | None) -> dict[str, Any] | None:
    if result.reference_kind is None or item is None:
        return None
    return {"kind": result.reference_kind.value, "amount": _dec(result.reference), "unit": item.reference.unit}


def _line(line: NewQuoteLine, result: LineResult, item: ItemReference | None, drift: Decimal | None) -> dict[str, Any]:
    return {
        "position": line.position, "description": line.description, "item_key": line.item_key,
        "quantity": _quantity(line.quantity), "unit": line.unit, "unit_price": _dec(line.unit_price),
        "amount": _dec(line.amount), "vat_included": line.vat_included,
        "unit_price_excl_vat": _dec(result.unit_price_excl_vat), "status": result.status.value,
        "reference": _reference(result, item), "rate_card": _dec(item.reference.rate_card) if item else None,
        "reference_as_of": item.label if item else None, "snapshot_as_of": _day(item.as_of) if item else None,
        "vs_rate_card_pct": _dec(result.vs_rate_card_pct), "vs_market_pct": _dec(result.vs_market_pct),
        "overcharge": _dec(result.overcharge), "vat_unknown": result.vat_unknown,
        "vs_reference_pct_if_vat_included": _dec(result.vs_reference_pct_if_vat_included),
        "low_confidence": result.low_confidence, "drift_pct": _dec(drift), "market": _market(item),
        "market_now": _stats(item.reference.market_now) if item else None,
    }  # fmt: skip


def _lines(outcome: ReviewOutcome, items: Mapping[str, ItemReference]) -> list[dict[str, Any]]:
    drift = outcome.result.drift_pct
    pairs = zip(outcome.reviewed, outcome.result.lines, strict=True)
    return [_line(ln, res, items.get(ln.item_key), drift.get(ln.item_key)) for ln, res in pairs]


def build_report(
    *, quote_id: UUID, review_id: UUID, facts: QuoteFacts, outcome: ReviewOutcome, plan: ReferencePlan
) -> dict[str, Any]:
    result = outcome.result
    lump = plan.items.get(LUMP_SUM_KEY) if facts.lump_sum else None
    return {
        "quote_id": str(quote_id), "review_id": str(review_id), "case_id": _id(facts.case_id),
        "vendor": {"id": _id(facts.vendor_id), "name": facts.vendor_name}, "currency": facts.currency,
        "total": _dec(facts.total), "verdict": result.verdict.value, "snapshot_basis": plan.basis.value,
        "decision_date": plan.decision_date.isoformat(), "quote_date": facts.quote_date.isoformat(),
        "work_date": _day(facts.work_date), "late_days": result.late_days, "late_flag": result.late_flag,
        "overcharge_total": _dec(result.overcharge_total),
        "overcharge_assumes_vat_excl_for_unknown_vat_lines": any(r.vat_unknown for r in result.lines),
        "low_confidence": result.low_confidence, "lump_sum": facts.lump_sum,
        "lump_sum_parts": lump.parts if lump is not None else [], "skipped_lines": len(outcome.skipped),
        "skipped": [{"position": ln.position, "description": ln.description} for ln in outcome.skipped],
        "reason": outcome.reason, "worst_line_index": result.worst_line_index, "lines": _lines(outcome, plan.items),
    }  # fmt: skip

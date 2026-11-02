"""What each quote item is compared with (spec 2026-10-31; rulings R18, R21). Pure: rows and lookups come in.

Basis: `decision_day` only when EVERY item of the quote has a snapshot of the case at or before the quote date;
otherwise the whole review is `estimate_current_prices`. Per item with a snapshot: the snapshot row's rate card
(immutable) and market figures, and the fresh lookup only as `market_now` (drift). Per item without one: the current
rate card on the quote date and the fresh lookup as the market (nothing is stored as a snapshot). `decision_date` =
the earliest snapshot used, else the quote date. A lump sum is compared, as ONE `job`, with the sum over the case's
snapshots of each item's rate card, else its market figure (quantity 1: snapshots store none).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.channels.prices.ports import PriceObservation
from app.contracts.finance import SnapshotBasis
from app.db.models import PriceSnapshot
from app.finance.review_types import Reference
from app.finance.snapshot import excl_vat_prices, source_entries
from app.finance.stats import MarketStats, aggregate

LUMP_SUM_KEY = "lump_sum"
LUMP_SUM_UNIT = "job"
UNNAMED_SOURCE = "unnamed source"


@dataclass(frozen=True)
class Fresh:
    """One lookup made for this review: its stats (None = no usable observation) and where each number came from."""

    stats: MarketStats | None
    sources: list[dict[str, str]]


@dataclass(frozen=True)
class ItemReference:
    """`as_of` = the snapshot day (None: estimated from current prices); `parts` = what a lump-sum figure sums."""

    reference: Reference
    sources: list[dict[str, str]]
    as_of: date | None
    parts: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ReferencePlan:
    basis: SnapshotBasis
    decision_date: date
    items: dict[str, ItemReference]

    @property
    def references(self) -> dict[str, Reference]:
        return {key: item.reference for key, item in self.items.items()}


def fresh_from(observations: Sequence[PriceObservation], unit: str, *, vat_rate: Decimal, min_samples: int) -> Fresh:
    found = excl_vat_prices(observations, unit, vat_rate)
    return Fresh(aggregate([price for _, price in found], min_samples), source_entries(found))


def snapshot_market(snap: PriceSnapshot, min_samples: int) -> MarketStats | None:
    """The stored market figures; None when the row cannot be a reference (a broken row is not a price)."""
    try:
        return MarketStats(
            low=snap.low, avg=snap.avg, high=snap.high, n=snap.sample_count, trimmed=False,
            low_confidence=snap.sample_count < min_samples,
        )  # fmt: skip
    except (ValueError, TypeError, ArithmeticError):
        return None


def _card(amount: Decimal | None) -> Decimal | None:
    return amount if amount is not None and amount > 0 else None


def named(entries: Sequence[Any]) -> list[dict[str, str]]:
    """Stored source entries as strings, each with a name."""
    out: list[dict[str, str]] = []
    for entry in entries:
        if isinstance(entry, dict):
            clean = {str(k): str(v) for k, v in entry.items() if v is not None}
            clean["name"] = clean.get("name") or UNNAMED_SOURCE
            out.append(clean)
    return out


def from_snapshot(snap: PriceSnapshot, fresh: Fresh | None, min_samples: int) -> ItemReference:
    now = fresh.stats if fresh is not None else None
    ref = Reference(
        unit=snap.unit,
        rate_card=_card(snap.rate_card_amount),
        market=snapshot_market(snap, min_samples),
        market_now=now,
    )
    return ItemReference(ref, named(snap.sources), snap.as_of)


def from_estimate(unit: str, card: Decimal | None, fresh: Fresh | None) -> ItemReference | None:
    market = fresh.stats if fresh is not None else None
    if _card(card) is None and market is None:
        return None
    return ItemReference(
        Reference(unit=unit, rate_card=_card(card), market=market), fresh.sources if fresh else [], None
    )


def plan_lines(
    units: Mapping[str, str],
    snapshots: Mapping[str, PriceSnapshot],
    cards: Mapping[str, Decimal | None],
    fresh: Mapping[str, Fresh],
    *,
    quote_date: date,
    min_samples: int,
) -> ReferencePlan:
    """`units`: the quote's item keys (first line's unit each); `snapshots` / `cards` / `fresh` keyed the same."""
    items: dict[str, ItemReference] = {}
    for key, unit in units.items():
        snap = snapshots.get(key)
        item = (
            from_snapshot(snap, fresh.get(key), min_samples)
            if snap
            else from_estimate(unit, cards.get(key), fresh.get(key))
        )
        if item is not None:
            items[key] = item
    used = [snapshots[key].as_of for key in units if key in snapshots]
    every = bool(units) and len(used) == len(units)
    basis = SnapshotBasis.decision_day if every else SnapshotBasis.estimate_current_prices
    return ReferencePlan(basis, min(used, default=quote_date), items)


@dataclass(frozen=True)
class _Part:
    item_key: str
    card: Decimal | None
    market: MarketStats | None

    def figures(self) -> tuple[Decimal, Decimal, Decimal] | None:
        """(low, avg, high) this item adds to a lump-sum reference: its rate card, else its market."""
        if self.card is not None:
            return self.card, self.card, self.card
        if self.market is not None:
            return self.market.low, self.market.avg, self.market.high
        return None

    def entry(self) -> dict[str, str]:
        kind, amount = (
            ("rate_card", self.card) if self.card is not None else ("market", self.market and self.market.avg)
        )
        return {"item_key": self.item_key, "kind": kind, "amount": str(amount)}


def _sum_stats(parts: Sequence[tuple[Decimal, Decimal, Decimal]], n: int) -> MarketStats:
    """A sum of items is not an observed market price: always `low_confidence`."""
    low, avg, high = (sum((p[i] for p in parts), Decimal(0)) for i in range(3))
    return MarketStats(low=low, avg=avg, high=high, n=n, trimmed=False, low_confidence=True)


def _lump_reference(parts: Sequence[_Part], n: int) -> Reference | None:
    figures = [f for p in parts if (f := p.figures()) is not None]
    if len(figures) < len(parts):
        return None  # an item with neither a card nor a market: the sum would understate the job
    cards = [p.card for p in parts if p.card is not None]
    if len(cards) < len(parts):
        return Reference(unit=LUMP_SUM_UNIT, market=_sum_stats(figures, n))
    markets = [(m.low, m.avg, m.high) for p in parts if (m := p.market) is not None]
    summed = _sum_stats(markets, n) if len(markets) == len(parts) else None
    return Reference(unit=LUMP_SUM_UNIT, rate_card=sum(cards, Decimal(0)), market=summed)


def plan_lump_sum(snapshots: Sequence[PriceSnapshot], *, quote_date: date, min_samples: int) -> ReferencePlan:
    """One `job` reference summing every item of the case's snapshots."""
    if not snapshots:
        return ReferencePlan(SnapshotBasis.estimate_current_prices, quote_date, {})
    decided = min(s.as_of for s in snapshots)
    parts = [_Part(s.item_key, _card(s.rate_card_amount), snapshot_market(s, min_samples)) for s in snapshots]
    ref = _lump_reference(parts, min(s.sample_count for s in snapshots))
    if ref is None:
        return ReferencePlan(SnapshotBasis.decision_day, decided, {})
    sources = [{**entry, "item_key": s.item_key} for s in snapshots for entry in named(s.sources)]
    item = ItemReference(ref, sources, decided, [p.entry() for p in parts])
    return ReferencePlan(SnapshotBasis.decision_day, decided, {LUMP_SUM_KEY: item})

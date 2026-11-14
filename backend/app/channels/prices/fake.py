"""Deterministic price source for dev and tests: same input, same output, no network."""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from app.channels.prices.ports import PriceObservation

SAMPLES = 5
MIN_BASE = 40
BASE_SPAN = 360  # base price lands in [40, 400)
SPREAD_PCT = (Decimal("-15"), Decimal("-7.5"), Decimal("0"), Decimal("7.5"), Decimal("15"))


class FakePriceSource:
    def __init__(self, table: Mapping[str, Sequence[Decimal]] | None = None) -> None:
        self._table = table or {}

    def lookup(self, item_key: str, unit: str, as_of: date) -> list[PriceObservation]:
        amounts = self._table.get(item_key) or self._derived(item_key)
        return [
            PriceObservation(
                amount=amount,
                unit=unit,
                vat_included=False,
                source="fake",
                url=f"https://prices.fake.invalid/{item_key}/{i}",
                observed_on=as_of,
            )
            for i, amount in enumerate(amounts)
        ]

    @staticmethod
    def _derived(item_key: str) -> list[Decimal]:
        digest = hashlib.sha256(item_key.encode()).digest()
        base = Decimal(MIN_BASE + int.from_bytes(digest[:4], "big") % BASE_SPAN)
        return [(base * (Decimal(100) + pct) / Decimal(100)).quantize(Decimal("0.01")) for pct in SPREAD_PCT]

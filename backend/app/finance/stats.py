"""Market price statistics over observed prices (excl. VAT). Pure: no I/O layers (import-linter contract).

Rules: zero observations → no stats (`None`). From 5 observations, values outside 1.5×IQR (quartiles by
`statistics.quantiles(method="inclusive")`) are dropped and `trimmed` says that something was dropped. Fewer
observations left than `min_samples` → stats are still returned, marked `low_confidence` (the review then gives no
verdict stronger than `needs_check`). `avg` is the mean rounded half-up to cents; `low`/`high` are observed values.
"""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
TRIM_FROM = 5  # the IQR rule needs enough points to have meaningful quartiles
IQR_FACTOR = Decimal("1.5")


@dataclass(frozen=True)
class MarketStats:
    low: Decimal
    avg: Decimal
    high: Decimal
    n: int
    trimmed: bool
    low_confidence: bool

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError("market stats need at least one observation")
        if not Decimal(0) < self.low <= self.avg <= self.high:
            raise ValueError("market stats must satisfy 0 < low <= avg <= high")


def _trim(values: list[Decimal]) -> list[Decimal]:
    if len(values) < TRIM_FROM:
        return values
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    spread = (q3 - q1) * IQR_FACTOR
    return [v for v in values if q1 - spread <= v <= q3 + spread]


def aggregate(observations: Sequence[Decimal], min_samples: int) -> MarketStats | None:
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    if any(v <= 0 for v in observations):
        raise ValueError("market observations must be positive")
    if not observations:
        return None
    values = sorted(observations)
    used = _trim(values)
    mean = (sum(used, Decimal(0)) / len(used)).quantize(CENT, rounding=ROUND_HALF_UP)
    return MarketStats(
        low=used[0],
        avg=min(max(mean, used[0]), used[-1]),  # rounding must not step outside sub-cent observations
        high=used[-1],
        n=len(used),
        trimmed=len(used) < len(values),
        low_confidence=len(used) < min_samples,
    )

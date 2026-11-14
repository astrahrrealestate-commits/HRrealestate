from decimal import Decimal

import pytest

from app.finance.stats import MarketStats, aggregate


def _d(*values: str) -> list[Decimal]:
    return [Decimal(v) for v in values]


def test_aggregate_returns_none_only_for_zero_observations() -> None:
    assert aggregate([], min_samples=3) is None


def test_aggregate_low_avg_high_with_mean_rounded_half_up() -> None:
    stats = aggregate(_d("100.00", "100.00", "100.01", "100.00"), min_samples=3)

    assert stats == MarketStats(
        low=Decimal("100.00"),
        avg=Decimal("100.00"),
        high=Decimal("100.01"),
        n=4,
        trimmed=False,
        low_confidence=False,
    )
    half = aggregate(_d("1.00", "1.01"), min_samples=1)
    assert half is not None
    assert half.avg == Decimal("1.01")  # 1.005 rounds half-up


def test_aggregate_below_min_samples_is_low_confidence_not_none() -> None:
    stats = aggregate(_d("80.00", "120.00"), min_samples=3)

    assert stats is not None
    assert stats.low_confidence is True
    assert (stats.low, stats.avg, stats.high, stats.n) == (Decimal("80.00"), Decimal("100.00"), Decimal("120.00"), 2)


def test_aggregate_trims_values_outside_one_and_a_half_iqr_from_five_observations() -> None:
    stats = aggregate(_d("100", "102", "98", "101", "99", "400"), min_samples=3)

    assert stats is not None
    assert stats.trimmed is True
    assert stats.n == 5
    assert stats.high == Decimal("102")
    assert stats.avg == Decimal("100.00")


def test_aggregate_does_not_trim_under_five_observations() -> None:
    stats = aggregate(_d("100", "101", "99", "400"), min_samples=3)

    assert stats is not None
    assert stats.trimmed is False
    assert stats.n == 4
    assert stats.high == Decimal("400")


def test_aggregate_without_outliers_is_not_marked_trimmed() -> None:
    stats = aggregate(_d("100", "101", "99", "102", "98"), min_samples=3)

    assert stats is not None
    assert (stats.trimmed, stats.n) == (False, 5)


def test_aggregate_low_confidence_counts_observations_left_after_trimming() -> None:
    stats = aggregate(_d("100", "101", "99", "100", "900"), min_samples=5)

    assert stats is not None
    assert (stats.n, stats.low_confidence) == (4, True)


@pytest.mark.parametrize("bad", [_d("0"), _d("-1", "10")])
def test_aggregate_rejects_non_positive_observations(bad: list[Decimal]) -> None:
    with pytest.raises(ValueError, match="positive"):
        aggregate(bad, min_samples=1)


def test_aggregate_rejects_min_samples_below_one() -> None:
    with pytest.raises(ValueError, match="min_samples"):
        aggregate(_d("1"), min_samples=0)


@pytest.mark.parametrize(("low", "avg", "high", "n"), [(5, 4, 6, 2), (0, 1, 2, 2), (1, 1, 1, 0)])
def test_market_stats_rejects_inconsistent_figures(low: int, avg: int, high: int, n: int) -> None:
    with pytest.raises(ValueError):
        MarketStats(low=Decimal(low), avg=Decimal(avg), high=Decimal(high), n=n, trimmed=False, low_confidence=False)

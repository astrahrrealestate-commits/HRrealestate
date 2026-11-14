"""Reference building for one quote review: decision-day snapshots vs estimates from current prices, lump sums."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.channels.prices.ports import PriceObservation
from app.contracts.finance import PriceBasis, SnapshotBasis
from app.db.models import PriceSnapshot
from app.finance.references import (
    LUMP_SUM_KEY,
    Fresh,
    fresh_from,
    plan_lines,
    plan_lump_sum,
    snapshot_market,
)
from app.finance.stats import MarketStats

DECIDED = date(2026, 10, 15)
QUOTED = date(2026, 10, 30)
NOW = MarketStats(low=Decimal(120), avg=Decimal(130), high=Decimal(140), n=3, trimmed=False, low_confidence=False)


def snap(
    key: str = "boiler_service", *, avg: str = "100", card: str | None = None, n: int = 3, as_of: date = DECIDED,
    unit: str = "job",
) -> PriceSnapshot:  # fmt: skip
    value = Decimal(avg)
    return PriceSnapshot(
        company_id=uuid4(), case_id=uuid4(), action_id=uuid4(), item_key=key, unit=unit, as_of=as_of,
        low=value - 10, avg=value, high=value + 10, sample_count=n, basis=PriceBasis.fake,
        sources=[{"name": "fake", "url": "https://prices.fake.invalid/x/0", "price": "90.00"}],
        rate_card_amount=Decimal(card) if card else None,
    )  # fmt: skip


def test_snapshot_market_reads_the_stored_row_and_flags_thin_samples() -> None:
    full = snapshot_market(snap(), min_samples=3)
    thin = snapshot_market(snap(n=2), min_samples=3)

    assert full == MarketStats(Decimal(90), Decimal(100), Decimal(110), 3, trimmed=False, low_confidence=False)
    assert thin is not None
    assert thin.low_confidence


def test_snapshot_market_of_a_broken_row_is_none() -> None:
    broken = snap(n=0)

    assert snapshot_market(broken, min_samples=3) is None


def test_decision_day_reference_uses_the_vendors_card_and_fresh_prices_only_for_drift() -> None:
    plan = plan_lines(
        {"boiler_service": "job"}, {"boiler_service": snap(card="80")}, {"boiler_service": Decimal(95)},
        {"boiler_service": Fresh(NOW, [])}, quote_date=QUOTED, min_samples=3,
    )  # fmt: skip

    item = plan.items["boiler_service"]
    assert (plan.basis, plan.decision_date) == (SnapshotBasis.decision_day, DECIDED)
    assert item.reference.rate_card == Decimal(95)  # the quoting vendor's card, as the caller resolved it
    assert item.reference.market is not None
    assert item.reference.market.avg == Decimal(100)
    assert item.reference.market_now == NOW
    assert (item.as_of, item.sources[0]["name"]) == (DECIDED, "fake")


def test_a_snapshot_card_is_never_used_unless_the_caller_passes_it() -> None:
    plan = plan_lines(
        {"boiler_service": "job"}, {"boiler_service": snap(card="80")}, {"boiler_service": None}, {},
        quote_date=QUOTED, min_samples=3,
    )  # fmt: skip

    assert plan.items["boiler_service"].reference.rate_card is None  # another contractor's card is no reference


def test_estimate_reference_uses_fresh_stats_and_the_current_card_without_drift() -> None:
    fresh = Fresh(NOW, [{"name": "fake", "url": "https://prices.fake.invalid/y/0", "price": "130.00"}])

    plan = plan_lines(
        {"leak_repair": "hour"}, {}, {"leak_repair": Decimal(60)}, {"leak_repair": fresh}, quote_date=QUOTED,
        min_samples=3,
    )  # fmt: skip

    item = plan.items["leak_repair"]
    assert (plan.basis, plan.decision_date) == (SnapshotBasis.estimate_current_prices, QUOTED)
    assert (item.reference.unit, item.reference.rate_card, item.reference.market) == ("hour", Decimal(60), NOW)
    assert (item.reference.market_now, item.as_of) == (None, None)
    assert item.sources == fresh.sources


def test_mixed_quote_is_an_estimate_but_keeps_the_decision_date_and_per_item_labels() -> None:
    plan = plan_lines(
        {"boiler_service": "job", "leak_repair": "hour"},
        {"boiler_service": snap(as_of=date(2026, 10, 12))},
        {"leak_repair": Decimal(60)},
        {"leak_repair": Fresh(NOW, [])},
        quote_date=QUOTED,
        min_samples=3,
    )

    assert plan.basis is SnapshotBasis.estimate_current_prices
    assert plan.decision_date == date(2026, 10, 12)  # the earliest snapshot used: lateness stays truthful
    assert (plan.items["boiler_service"].label, plan.items["leak_repair"].label) == ("decision_day", "estimate")
    assert plan.items["leak_repair"].reference.rate_card == Decimal(60)


def test_an_item_with_no_card_and_no_prices_has_no_reference() -> None:
    plan = plan_lines(
        {"painting": "job"}, {}, {"painting": None}, {"painting": Fresh(None, [])}, quote_date=QUOTED, min_samples=3
    )

    assert plan.items == {}


def test_non_positive_card_is_ignored() -> None:
    plan = plan_lines({"boiler_service": "job"}, {"boiler_service": snap()}, {"boiler_service": Decimal(0)}, {},
                      quote_date=QUOTED, min_samples=3)  # fmt: skip

    assert plan.items["boiler_service"].reference.rate_card is None


def test_lump_sum_reference_sums_the_vendors_card_else_the_market_average() -> None:
    snaps = [snap(card="80"), snap("leak_repair", avg="60", card="70", unit="hour")]

    plan = plan_lump_sum(snaps, {"boiler_service": Decimal(95)}, quote_date=QUOTED, min_samples=3)

    item = plan.items[LUMP_SUM_KEY]
    assert (plan.basis, plan.decision_date) == (SnapshotBasis.decision_day, DECIDED)
    assert (item.reference.unit, item.reference.rate_card, item.label) == ("job", None, "decision_day")
    assert item.reference.market is not None
    assert (item.reference.market.low, item.reference.market.avg, item.reference.market.high) == (
        Decimal(145), Decimal(155), Decimal(165),
    )  # fmt: skip
    assert item.reference.market.low_confidence  # a sum of items is not an observed market price
    assert item.parts == [
        {"item_key": "boiler_service", "kind": "rate_card", "amount": "95"},
        {"item_key": "leak_repair", "kind": "market", "amount": "60"},  # the snapshot's 70 is not this vendor's
    ]


def test_lump_sum_with_every_card_compares_with_the_summed_cards() -> None:
    cards = {"boiler_service": Decimal(95), "leak_repair": Decimal(70)}

    plan = plan_lump_sum([snap(), snap("leak_repair", avg="60")], cards, quote_date=QUOTED, min_samples=3)

    ref = plan.items[LUMP_SUM_KEY].reference
    assert ref.rate_card == Decimal(165)
    assert ref.market is not None
    assert ref.market.avg == Decimal(160)


def test_lump_sum_without_snapshots_has_no_reference() -> None:
    plan = plan_lump_sum([], {}, quote_date=QUOTED, min_samples=3)

    assert (plan.basis, plan.decision_date, plan.items) == (SnapshotBasis.estimate_current_prices, QUOTED, {})


def test_fresh_from_aggregates_excl_vat_prices_with_their_sources() -> None:
    seen = [
        PriceObservation(Decimal("121"), "uur", True, "fake", "https://prices.fake.invalid/a/0", QUOTED),
        PriceObservation(Decimal("110"), "hour", False, "competitor:Rival BV", None, QUOTED),
        PriceObservation(Decimal("999"), "job", False, "fake", "https://prices.fake.invalid/a/1", QUOTED),
    ]

    fresh = fresh_from(seen, "hour", vat_rate=Decimal("0.21"), min_samples=3)

    assert fresh.stats is not None
    assert (fresh.stats.low, fresh.stats.avg, fresh.stats.n, fresh.stats.low_confidence) == (
        Decimal(100), Decimal(105), 2, True,
    )  # fmt: skip
    assert [s["name"] for s in fresh.sources] == ["fake", "competitor:Rival BV"]

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts.finance import LineStatus, SnapshotBasis, Verdict
from app.finance.review import review_quote, to_excl_vat
from app.finance.review_types import (
    SEVERITY,
    Reference,
    ReferenceKind,
    ReviewInput,
    ReviewLine,
    Thresholds,
)
from app.finance.stats import MarketStats

T = Thresholds(
    ok_pct=Decimal(5),
    above_market_pct=Decimal(15),
    well_above_pct=Decimal(30),
    low_ratio=Decimal("0.5"),
    late_days=7,
    min_samples=3,
    vat_rate=Decimal("0.21"),
)
ITEM = "boiler_service"


def market(avg: str, *, low_confidence: bool = False) -> MarketStats:
    value = Decimal(avg)
    return MarketStats(low=value, avg=value, high=value, n=5, trimmed=False, low_confidence=low_confidence)


def ref(
    *, rate_card: str | None = None, avg: str | None = None, unit: str = "job", low_confidence: bool = False
) -> Reference:
    return Reference(
        unit=unit,
        rate_card=Decimal(rate_card) if rate_card else None,
        market=market(avg, low_confidence=low_confidence) if avg else None,
    )


def line(
    price: str,
    *,
    qty: str = "1",
    unit: str = "job",
    item: str | None = ITEM,
    vat: bool | None = False,
    currency: str | None = None,
) -> ReviewLine:
    unit_price = Decimal(price)
    return ReviewLine(
        description="Ketel onderhoud",
        quantity=Decimal(qty),
        unit=unit,
        unit_price=unit_price,
        amount=unit_price * Decimal(qty),
        vat_included=vat,
        item_key=item,
        currency=currency,
    )


def quote(
    *lines: ReviewLine,
    refs: dict[str, Reference],
    basis: SnapshotBasis = SnapshotBasis.decision_day,
    decided: date = date(2026, 10, 15),
    quoted: date = date(2026, 10, 15),
    vat: bool | None = None,
    lump_sum: bool = False,
) -> ReviewInput:
    return ReviewInput(
        lines=tuple(lines),
        currency="EUR",
        quote_date=quoted,
        decision_date=decided,
        references=refs,
        snapshot_basis=basis,
        vat_included=vat,
        lump_sum=lump_sum,
    )


def status_of(price: str, reference: Reference) -> LineStatus:
    return review_quote(quote(line(price), refs={ITEM: reference}), T).lines[0].status


def test_within_five_percent_is_ok() -> None:
    result = review_quote(quote(line("105.00"), refs={ITEM: ref(rate_card="100")}), T)

    assert result.lines[0].status is LineStatus.ok
    assert result.lines[0].vs_rate_card_pct == Decimal("5.00")
    assert result.verdict is Verdict.ok
    assert result.low_confidence is False
    assert status_of("95.00", ref(rate_card="100")) is LineStatus.ok
    assert status_of("105.00", ref(avg="100")) is LineStatus.ok


def test_rate_card_beats_market_as_reference() -> None:
    result = review_quote(quote(line("150.00"), refs={ITEM: ref(rate_card="100", avg="200")}), T)

    first = result.lines[0]
    assert (first.reference, first.reference_kind) == (Decimal("100"), ReferenceKind.rate_card)
    assert first.status is LineStatus.above_agreed
    assert first.vs_rate_card_pct == Decimal("50.00")
    assert first.vs_market_pct == Decimal("-25.00")


def test_above_agreed_over_five_percent_of_rate_card() -> None:
    result = review_quote(quote(line("105.01"), refs={ITEM: ref(rate_card="100")}), T)

    assert result.lines[0].status is LineStatus.above_agreed
    assert result.verdict is Verdict.above_agreed


def test_fifteen_to_thirty_is_above_market_and_over_thirty_well_above() -> None:
    reference = ref(avg="100")

    assert status_of("115.00", reference) is LineStatus.ok
    assert status_of("115.01", reference) is LineStatus.above_market
    assert status_of("130.00", reference) is LineStatus.above_market
    assert status_of("130.01", reference) is LineStatus.well_above_market
    well = review_quote(quote(line("140.00"), refs={ITEM: reference}), T)
    assert well.verdict is Verdict.well_above_market
    assert well.lines[0].vs_market_pct == Decimal("40.00")


def test_under_half_of_market_is_suspiciously_low() -> None:
    result = review_quote(quote(line("49.99"), refs={ITEM: ref(avg="100")}), T)

    assert result.lines[0].status is LineStatus.suspiciously_low
    assert result.verdict is Verdict.needs_check
    assert status_of("50.00", ref(avg="100")) is LineStatus.ok
    assert status_of("49.99", ref(rate_card="100")) is LineStatus.suspiciously_low


def test_no_reference_never_ok_and_caps_verdict_at_needs_check() -> None:
    unknown = review_quote(quote(line("9999.00", item="roof_repair"), refs={ITEM: ref(rate_card="100")}), T)
    per_hour = review_quote(quote(line("9999.00", unit="uur"), refs={ITEM: ref(rate_card="100")}), T)
    empty_ref = review_quote(quote(line("100.00"), refs={ITEM: Reference(unit="job")}), T)
    unmatched = review_quote(quote(line("100.00", item=None), refs={}), T)
    mixed = review_quote(quote(line("100.00"), line("50.00", item="other"), refs={ITEM: ref(rate_card="100")}), T)

    for result in (unknown, per_hour, empty_ref, unmatched):
        assert result.lines[0].status is LineStatus.no_reference
        assert result.lines[0].overcharge is None
        assert result.verdict is Verdict.needs_check
    assert mixed.verdict is Verdict.needs_check
    assert review_quote(quote(refs={}), T).verdict is Verdict.needs_check


def test_unit_match_ignores_case_and_surrounding_space() -> None:
    assert status_of("100.00", ref(rate_card="100", unit=" JOB ")) is LineStatus.ok


def test_estimate_basis_caps_verdict_at_needs_check() -> None:
    estimate = SnapshotBasis.estimate_current_prices
    capped = review_quote(quote(line("200.00"), refs={ITEM: ref(avg="100")}, basis=estimate), T)
    fine = review_quote(quote(line("100.00"), refs={ITEM: ref(avg="100")}, basis=estimate), T)

    assert capped.lines[0].status is LineStatus.well_above_market
    assert capped.verdict is Verdict.needs_check
    assert capped.low_confidence is True
    assert fine.lines[0].status is LineStatus.ok
    assert fine.verdict is Verdict.needs_check  # an estimate never says "fair on the decision day"
    assert fine.low_confidence is True


def test_low_confidence_market_reference_caps_and_never_says_ok() -> None:
    thin = {ITEM: ref(avg="100", low_confidence=True)}

    assert review_quote(quote(line("200.00"), refs=thin), T).verdict is Verdict.needs_check
    ok_price = review_quote(quote(line("100.00"), refs=thin), T)
    assert (ok_price.verdict, ok_price.low_confidence) == (Verdict.needs_check, True)
    rate_card = review_quote(
        quote(line("200.00"), refs={ITEM: ref(rate_card="100", avg="100", low_confidence=True)}), T
    )
    assert (rate_card.verdict, rate_card.low_confidence) == (Verdict.above_agreed, False)


def test_late_days_is_quote_minus_decision_and_flags_at_seven_and_clamps_negative_to_zero() -> None:
    def late(quoted: date) -> tuple[int, bool]:
        result = review_quote(quote(line("100"), refs={ITEM: ref(rate_card="100")}, quoted=quoted), T)
        return result.late_days, result.late_flag

    assert late(date(2026, 10, 30)) == (15, True)
    assert late(date(2026, 10, 22)) == (7, True)
    assert late(date(2026, 10, 21)) == (6, False)
    assert late(date(2026, 10, 10)) == (0, False)


def test_currency_mismatch_line_is_not_compared() -> None:
    result = review_quote(quote(line("100.00", currency="USD"), refs={ITEM: ref(rate_card="100", avg="100")}), T)

    first = result.lines[0]
    assert first.status is LineStatus.currency_mismatch
    assert (first.reference, first.vs_rate_card_pct, first.vs_market_pct, first.overcharge) == (None, None, None, None)
    assert result.verdict is Verdict.needs_check
    assert result.overcharge_total == Decimal("0.00")


def test_vat_included_is_normalised_before_compare() -> None:
    result = review_quote(quote(line("121.00", vat=True), refs={ITEM: ref(rate_card="100.00")}), T)
    from_quote_flag = review_quote(quote(line("121.00", vat=None), refs={ITEM: ref(rate_card="100.00")}, vat=True), T)

    assert result.lines[0].unit_price_excl_vat == Decimal("100.00")
    assert result.lines[0].status is LineStatus.ok
    assert result.verdict is Verdict.ok
    assert from_quote_flag.verdict is Verdict.ok
    assert from_quote_flag.lines[0].vat_unknown is False


def test_vat_unknown_compares_as_stated_and_shows_the_incl_vat_reading() -> None:
    result = review_quote(quote(line("121.00", vat=None), refs={ITEM: ref(rate_card="100.00")}), T)

    first = result.lines[0]
    assert first.vat_unknown is True
    assert first.status is LineStatus.above_agreed
    assert first.vs_rate_card_pct == Decimal("21.00")
    assert first.vs_reference_pct_if_vat_included == Decimal("0.00")
    assert (result.verdict, result.low_confidence) == (Verdict.needs_check, True)
    at_par = review_quote(quote(line("100.00", vat=None), refs={ITEM: ref(rate_card="100.00")}), T)
    assert at_par.verdict is Verdict.needs_check


def test_to_excl_vat() -> None:
    rate = Decimal("0.21")

    assert to_excl_vat(Decimal("121.00"), True, rate) == Decimal("100.00")
    assert to_excl_vat(Decimal("10.00"), True, rate) == Decimal("8.26")  # 8.2644… half-up
    assert to_excl_vat(Decimal("99.99"), False, rate) == Decimal("99.99")
    assert to_excl_vat(Decimal("99.99"), None, rate) is None


def test_missing_unit_price_uses_amount_over_quantity() -> None:
    no_unit = ReviewLine(
        description="Lekkage",
        quantity=Decimal(2),
        unit="uur",
        unit_price=None,
        amount=Decimal("242.00"),
        vat_included=True,
        item_key="leak_repair_hourly",
    )
    result = review_quote(quote(no_unit, refs={"leak_repair_hourly": ref(rate_card="100", unit="uur")}), T)

    assert result.lines[0].unit_price_excl_vat == Decimal("100.00")
    assert result.lines[0].status is LineStatus.ok


def test_overcharge_never_negative() -> None:
    refs = {ITEM: ref(rate_card="100"), "callout": ref(avg="50")}
    result = review_quote(quote(line("80.00"), line("75.00", qty="2", item="callout"), refs=refs), T)

    assert result.lines[0].overcharge == Decimal("0.00")
    assert result.lines[1].overcharge == Decimal("50.00")
    assert result.overcharge_total == Decimal("50.00")


def test_verdict_is_most_severe_line_and_worst_line_is_the_largest_amount() -> None:
    refs = {ITEM: ref(rate_card="100"), "callout": ref(avg="100"), "parts": ref(avg="100")}
    lines = (
        line("100.00", qty="50"),  # ok, by far the largest amount
        line("120.00", item="callout"),  # above_market, 120
        line("125.00", qty="3", item="parts"),  # above_market, 375
        line("106.00"),  # above_agreed, small
    )

    above_market = review_quote(quote(*lines[:3], refs=refs), T)
    assert (above_market.verdict, above_market.worst_line_index) == (Verdict.above_market, 2)
    above_agreed = review_quote(quote(*lines, refs=refs), T)
    assert (above_agreed.verdict, above_agreed.worst_line_index) == (Verdict.above_agreed, 3)
    assert review_quote(quote(refs={}), T).worst_line_index is None


def test_drift_shows_market_move_between_snapshot_and_now() -> None:
    moved = Reference(unit="job", market=market("100"), market_now=market("110"))
    no_now = Reference(unit="job", market=market("100"))
    result = review_quote(quote(line("100"), refs={ITEM: moved, "callout": no_now}), T)

    assert result.drift_pct == {ITEM: Decimal("10.00"), "callout": None}


def test_lump_sum_single_line_capped() -> None:
    flagged = review_quote(quote(line("500.00"), refs={ITEM: ref(rate_card="100")}, lump_sum=True), T)
    at_card = review_quote(quote(line("100.00"), refs={ITEM: ref(rate_card="100")}, lump_sum=True), T)
    two_items = {ITEM: ref(rate_card="100"), "callout": ref(rate_card="50")}
    derived = review_quote(quote(line("500.00"), refs=two_items), T)

    assert (flagged.verdict, flagged.low_confidence) == (Verdict.needs_check, True)
    assert at_card.verdict is Verdict.needs_check
    assert (derived.verdict, derived.low_confidence) == (Verdict.needs_check, True)


def test_reference_rejects_non_positive_rate_card() -> None:
    with pytest.raises(ValueError):
        Reference(unit="job", rate_card=Decimal(0))


@pytest.mark.parametrize(("qty", "unit_price"), [("0", None), ("-1", "10"), ("1", "0"), ("2", "-5")])
def test_review_line_rejects_non_positive_quantity_and_unit_price(qty: str, unit_price: str | None) -> None:
    with pytest.raises(ValueError):
        ReviewLine(
            description="Ketel onderhoud",
            quantity=Decimal(qty),
            unit="job",
            amount=Decimal(10),
            unit_price=Decimal(unit_price) if unit_price is not None else None,
        )


def test_line_currency_is_compared_case_insensitively() -> None:
    lower = review_quote(quote(line("100.00", currency="eur"), refs={ITEM: ref(rate_card="100")}), T)
    mixed = review_quote(quote(line("100.00", currency=" Eur "), refs={ITEM: ref(rate_card="100")}), T)

    assert lower.lines[0].status is mixed.lines[0].status is LineStatus.ok
    assert lower.verdict is Verdict.ok


def test_uncompared_lines_are_flagged_low_confidence_but_do_not_hide_a_firm_finding() -> None:
    refs = {ITEM: ref(avg="100")}
    no_ref = review_quote(quote(line("100.00", item="roof_repair"), refs=refs), T)
    usd = review_quote(quote(line("100.00", currency="USD"), refs=refs), T)
    mixed = review_quote(quote(line("200.00"), line("50.00", item="roof_repair"), refs=refs), T)

    for result in (no_ref, usd):
        assert result.lines[0].low_confidence is True  # explains the bare needs_check
        assert result.verdict is Verdict.needs_check
    assert mixed.lines[1].low_confidence is True
    assert mixed.verdict is Verdict.well_above_market  # an unchecked line floors, it never caps a firm finding
    assert mixed.low_confidence is False


_REFERENCE = st.decimals(min_value=Decimal("1.00"), max_value=Decimal(5000), places=2)
_STEP = st.decimals(min_value=Decimal(0), max_value=Decimal(5000), places=2)
_RATIO = st.decimals(min_value=Decimal("0.51"), max_value=Decimal(3), places=2)


@given(
    reference=_REFERENCE,
    ratio=_RATIO,
    step=_STEP,
    use_rate_card=st.booleans(),
    vat=st.sampled_from([True, False, None]),
    basis=st.sampled_from(list(SnapshotBasis)),
    thin=st.booleans(),
    other=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(500), places=2),
)
def test_verdict_is_monotonic_in_price(
    reference: Decimal,
    ratio: Decimal,
    step: Decimal,
    use_rate_card: bool,
    vat: bool | None,
    basis: SnapshotBasis,
    thin: bool,
    other: Decimal,
) -> None:
    """Bound: prices start at or above the suspiciously_low band (low_ratio x reference, excl. VAT); below it a
    rise from `suspiciously_low` (needs_check) to `ok` is an intended improvement."""
    refs = {
        ITEM: ref(rate_card=str(reference)) if use_rate_card else ref(avg=str(reference), low_confidence=thin),
        "callout": ref(avg="100"),
    }
    vat_factor = Decimal("1.21") if vat else Decimal(1)
    base = (reference * ratio * vat_factor).quantize(Decimal("0.01"))

    def verdict(price: Decimal) -> Verdict:
        priced = line(str(price), vat=vat)
        return review_quote(quote(priced, line(str(other), item="callout"), refs=refs, basis=basis), T).verdict

    assert SEVERITY[verdict(base + step)] >= SEVERITY[verdict(base)]
    if basis is SnapshotBasis.estimate_current_prices:
        assert verdict(base) is verdict(base + step) is Verdict.needs_check

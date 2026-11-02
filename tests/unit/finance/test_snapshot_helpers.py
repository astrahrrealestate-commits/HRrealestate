from datetime import date
from decimal import Decimal

from app.channels.prices.ports import PriceObservation
from app.contracts.finance import JobItem, PriceBasis
from app.finance.snapshot import basis_of, excl_vat_prices, job_keys, source_entries

DAY = date(2026, 10, 15)
VAT = Decimal("0.21")


def obs(
    source: str, amount: str = "100", *, url: str | None = "https://x.example/p", vat: bool = False, unit: str = "hour"
) -> PriceObservation:
    url = None if source == "owner" or source.startswith("competitor:") else url
    return PriceObservation(
        amount=Decimal(amount), unit=unit, vat_included=vat, source=source, url=url, observed_on=DAY
    )


def test_basis_all_fake_is_fake() -> None:
    assert basis_of([obs("fake"), obs("fake")]) is PriceBasis.fake


def test_basis_single_kinds() -> None:
    assert basis_of([obs("Werkspot")]) is PriceBasis.web
    assert basis_of([obs("competitor:Rival BV")]) is PriceBasis.competitor
    assert basis_of([obs("owner")]) is PriceBasis.owner


def test_basis_mixed_takes_the_dominant_and_ties_prefer_web() -> None:
    two_rivals = [obs("competitor:A"), obs("competitor:B"), obs("Werkspot")]
    tie = [obs("competitor:A"), obs("Werkspot")]
    fake_and_rival = [obs("fake"), obs("fake"), obs("competitor:A")]

    assert basis_of(two_rivals) is PriceBasis.competitor
    assert basis_of(tie) is PriceBasis.web
    assert basis_of(fake_and_rival) is PriceBasis.fake


def test_excl_vat_prices_strip_vat_and_drop_other_units() -> None:
    prices = excl_vat_prices([obs("a", "121", vat=True), obs("b", "90"), obs("c", "50", unit="dag")], "uur", VAT)

    assert [(o.source, p) for o, p in prices] == [("a", Decimal("100.00")), ("b", Decimal("90"))]


def test_source_entries_are_strings_and_always_named() -> None:
    entries = source_entries([(obs("Werkspot"), Decimal("100.00")), (obs("competitor:Rival"), Decimal("80"))])

    assert entries == [
        {"name": "Werkspot", "url": "https://x.example/p", "price": "100.00", "observed_on": "2026-10-15"},
        {"name": "competitor:Rival", "price": "80.00", "observed_on": "2026-10-15"},
    ]
    assert all(isinstance(v, str) for e in entries for v in e.values())


def test_job_keys_normalise_and_keep_the_first_of_a_key() -> None:
    items = [
        JobItem(description="Cv ketel onderhoud", quantity=Decimal(1), unit="klus"),
        JobItem(description="Boiler service", quantity=Decimal(1), unit="job"),
        JobItem(description="Lekkage herstel", quantity=Decimal(2), unit="uren"),
    ]

    assert job_keys(items) == [("boiler_service", "job"), ("leak_repair", "hour")]

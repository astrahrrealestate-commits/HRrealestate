"""Quote facts from the extracted quote, and the guarded review of stored lines (unreadable lines are skipped)."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.contracts.finance import ExtractedQuote, LineStatus, SnapshotBasis, Verdict
from app.core.settings import Settings
from app.finance.config import thresholds_from_settings
from app.finance.quote_lines import QuoteFacts, quote_currency, run_review, stored_lines
from app.finance.references import LUMP_SUM_KEY, ItemReference, ReferencePlan
from app.finance.repo_quotes import NewQuoteLine
from app.finance.review_types import Reference
from app.finance.stats import MarketStats

DECIDED = date(2026, 10, 15)
QUOTED = date(2026, 10, 30)
THRESHOLDS = thresholds_from_settings(
    Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[arg-type]
)
MARKET = MarketStats(low=Decimal(90), avg=Decimal(100), high=Decimal(110), n=3, trimmed=False, low_confidence=False)


def money(amount: str, currency: str = "EUR") -> dict[str, str]:
    return {"amount": amount, "currency": currency}


def extracted(lines: list[dict[str, Any]], *, total: dict[str, str] | None = None, vat: bool | None = None) -> Any:
    return ExtractedQuote.model_validate(
        {"lines": lines, "total": total, "quote_date": None, "work_date": None, "vat_included": vat, "is_quote": True}
    )


def qline(desc: str, amount: str, *, unit: str = "uur", qty: str = "2", price: str | None = None,
          vat: bool | None = None, currency: str = "EUR") -> dict[str, Any]:  # fmt: skip
    return {
        "description": desc, "quantity": qty, "unit": unit, "unit_price": money(price, currency) if price else None,
        "amount": money(amount, currency), "vat_included": vat,
    }  # fmt: skip


def facts(lines: list[NewQuoteLine], currency: str = "EUR") -> QuoteFacts:
    return QuoteFacts(
        company_id=uuid4(), case_id=uuid4(), vendor_id=uuid4(), vendor_name="Vendor BV", currency=currency,
        total=None, quote_date=QUOTED, lines=tuple(lines),
    )  # fmt: skip


def plan(key: str = "boiler_service", unit: str = "job") -> ReferencePlan:
    ref = Reference(unit=unit, market=MARKET)
    return ReferencePlan(SnapshotBasis.decision_day, DECIDED, {key: ItemReference(ref, [], DECIDED)})


def line(position: int, amount: str, *, qty: str = "1", price: str | None = None) -> NewQuoteLine:
    return NewQuoteLine(
        position=position, description="Cv ketel onderhoud", item_key="boiler_service", quantity=Decimal(qty),
        unit="job", amount=Decimal(amount), unit_price=Decimal(price) if price else None, vat_included=False,
    )  # fmt: skip


def test_extracted_lines_get_item_keys_canonical_units_and_the_quote_vat_fallback() -> None:
    quote = extracted([qline("Lekkage herstel", "120.00", price="60.00"), qline("Cv ketel onderhoud", "95.00",
                                                                                 unit="klus", qty="1", vat=True)],
                      vat=False)  # fmt: skip

    first, second = stored_lines(quote)

    assert (first.position, first.item_key, first.unit, first.unit_price, first.vat_included) == (
        1, "leak_repair", "hour", Decimal(60), False,
    )  # fmt: skip
    assert (second.position, second.item_key, second.unit, second.vat_included) == (2, "boiler_service", "job", True)


def test_lump_sum_becomes_one_synthetic_line() -> None:
    quote = extracted([], total=money("450.00"), vat=False)

    (only,) = stored_lines(quote)

    assert (only.item_key, only.description, only.quantity, only.unit, only.amount, only.vat_included) == (
        LUMP_SUM_KEY, "lump sum", Decimal(1), "job", Decimal(450), False,
    )  # fmt: skip
    assert facts([only]).lump_sum
    assert not facts([line(1, "100")]).lump_sum


def test_a_mixed_currency_quote_takes_its_foreign_currency() -> None:
    euro = extracted([qline("Arbeid", "120.00")], total=money("120.00"))  # the contract only allows upper case
    mixed = extracted([qline("Arbeid", "120.00"), qline("Materiaal", "45.00", currency="USD")])

    assert quote_currency(euro) == "EUR"
    assert quote_currency(mixed) == "USD"
    assert quote_currency(extracted([])) == "EUR"


def test_review_runs_on_readable_lines() -> None:
    out = run_review(facts([line(1, "131.00")]), plan(), THRESHOLDS)

    assert out.result.verdict is Verdict.well_above_market
    assert (out.skipped, out.reason, len(out.reviewed)) == ((), None, 1)


def test_unreadable_line_is_skipped_and_forces_needs_check_with_low_confidence() -> None:
    bad_qty = line(2, "50.00", qty="0")
    bad_price = line(3, "50.00", price="-1")
    bad_amount = line(4, "0")

    out = run_review(facts([line(1, "131.00"), bad_qty, bad_price, bad_amount]), plan(), THRESHOLDS)

    assert out.skipped == (bad_qty, bad_price, bad_amount)
    assert [ln.position for ln in out.reviewed] == [1]
    assert out.result.lines[0].status is LineStatus.well_above_market
    assert (out.result.verdict, out.result.low_confidence) == (Verdict.needs_check, True)
    assert out.reason == "3 unreadable line(s) skipped"


def test_every_line_unreadable_still_reviews_as_needs_check_with_the_reason() -> None:
    out = run_review(facts([line(1, "10", qty="-2")]), plan(), THRESHOLDS)

    assert (out.result.verdict, out.result.low_confidence, out.result.lines) == (Verdict.needs_check, True, [])
    assert out.reason == "no readable quote lines"


def test_foreign_currency_quote_is_a_currency_mismatch() -> None:
    out = run_review(facts([line(1, "131.00")], currency="USD"), plan(), THRESHOLDS)

    assert out.result.lines[0].status is LineStatus.currency_mismatch
    assert out.result.verdict is Verdict.needs_check


def test_lump_sum_review_is_flagged_and_capped() -> None:
    (only,) = stored_lines(extracted([], total=money("450.00"), vat=False))

    out = run_review(facts([only]), plan(LUMP_SUM_KEY), THRESHOLDS)

    assert out.review_input.lump_sum
    assert (out.result.verdict, out.result.low_confidence) == (Verdict.needs_check, True)

"""Owner feed card / API payload of one quote review: JSON-serialisable, Decimals as strings, dates ISO."""

import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.contracts.finance import SnapshotBasis
from app.core.settings import Settings
from app.finance.config import thresholds_from_settings
from app.finance.quote_lines import QuoteFacts, run_review
from app.finance.references import ItemReference, ReferencePlan
from app.finance.repo_quotes import NewQuoteLine
from app.finance.report import build_report
from app.finance.review_types import Reference
from app.finance.stats import MarketStats

DECIDED = date(2026, 10, 15)
QUOTED = date(2026, 10, 30)
SETTINGS = Settings(database_url="postgresql+psycopg://u:p@localhost:1/db", _env_file=None)  # type: ignore[arg-type]
THRESHOLDS = thresholds_from_settings(SETTINGS)
SOURCE = {"name": "fake", "url": "https://prices.fake.invalid/boiler_service/0", "price": "90.00"}
THEN = MarketStats(low=Decimal(90), avg=Decimal(100), high=Decimal(110), n=3, trimmed=False, low_confidence=False)
NOW = MarketStats(low=Decimal(120), avg=Decimal(130), high=Decimal(140), n=3, trimmed=False, low_confidence=False)
QUOTE_ID, REVIEW_ID = uuid4(), uuid4()


def _line(position: int, amount: str, *, vat: bool | None = False, qty: str = "1") -> NewQuoteLine:
    return NewQuoteLine(
        position=position, description="Cv ketel onderhoud", item_key="boiler_service", quantity=Decimal(qty),
        unit="job", amount=Decimal(amount), vat_included=vat,
    )  # fmt: skip


def _report(*lines: NewQuoteLine) -> dict[str, Any]:
    facts = QuoteFacts(
        company_id=uuid4(), case_id=uuid4(), vendor_id=uuid4(), vendor_name="Vendor BV", currency="EUR",
        total=Decimal("131.00"), quote_date=QUOTED, lines=lines,
    )  # fmt: skip
    ref = Reference(unit="job", rate_card=Decimal(95), market=THEN, market_now=NOW)
    plan = ReferencePlan(SnapshotBasis.decision_day, DECIDED, {"boiler_service": ItemReference(ref, [SOURCE], DECIDED)})
    return build_report(
        quote_id=QUOTE_ID, review_id=REVIEW_ID, facts=facts, outcome=run_review(facts, plan, THRESHOLDS), plan=plan
    )


def _floats(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for v in value.values() for f in _floats(v)]
    if isinstance(value, list):
        return [f for v in value for f in _floats(v)]
    return []


def test_report_is_plain_json_with_decimal_strings_and_iso_dates() -> None:
    report = _report(_line(1, "131.00"))

    assert json.loads(json.dumps(report)) == report  # no Decimal, date or UUID objects left
    assert _floats(report) == []
    assert (report["quote_id"], report["review_id"]) == (str(QUOTE_ID), str(REVIEW_ID))
    assert UUID(report["case_id"])
    assert (report["vendor"]["name"], report["currency"], report["total"]) == ("Vendor BV", "EUR", "131.00")
    assert (report["quote_date"], report["decision_date"]) == ("2026-10-30", "2026-10-15")


def test_report_top_level_fields() -> None:
    report = _report(_line(1, "131.00"))

    assert {k: report[k] for k in ("verdict", "snapshot_basis", "late_days", "late_flag", "overcharge_total")} == {
        "verdict": "above_agreed", "snapshot_basis": "decision_day", "late_days": 15, "late_flag": True,
        "overcharge_total": "36.00",
    }  # fmt: skip
    assert (report["low_confidence"], report["lump_sum"], report["skipped_lines"], report["reason"]) == (
        False, False, 0, None,
    )  # fmt: skip
    assert report["overcharge_assumes_vat_excl_for_unknown_vat_lines"] is False


def test_report_line_has_reference_market_sources_and_drift() -> None:
    (line,) = _report(_line(1, "131.00"))["lines"]

    assert line["reference"] == {"kind": "rate_card", "amount": "95", "unit": "job"}
    assert {k: line[k] for k in ("status", "vs_rate_card_pct", "vs_market_pct", "overcharge", "drift_pct")} == {
        "status": "above_agreed", "vs_rate_card_pct": "37.89", "vs_market_pct": "31.00", "overcharge": "36.00",
        "drift_pct": "30.00",
    }  # fmt: skip
    assert (line["description"], line["item_key"], line["quantity"], line["unit"], line["amount"]) == (
        "Cv ketel onderhoud", "boiler_service", "1", "job", "131.00",
    )  # fmt: skip
    assert line["unit_price_excl_vat"] == "131.00"
    assert line["market"] == {
        "low": "90", "avg": "100", "high": "110", "n": 3, "low_confidence": False,
        "sources": [{"name": "fake", "url": SOURCE["url"], "price": "90.00"}],
    }  # fmt: skip
    assert (line["vat_unknown"], line["vs_reference_pct_if_vat_included"]) == (False, None)


def test_report_shows_the_vat_assumption_for_unknown_vat_lines() -> None:
    report = _report(_line(1, "131.00", vat=None))

    (line,) = report["lines"]
    assert (line["vat_unknown"], line["vs_reference_pct_if_vat_included"]) == (True, "13.96")
    assert report["overcharge_assumes_vat_excl_for_unknown_vat_lines"] is True
    assert (report["verdict"], report["low_confidence"]) == ("needs_check", True)


def test_report_lists_skipped_lines() -> None:
    report = _report(_line(1, "131.00"), _line(2, "50.00", qty="0"))

    assert (report["skipped_lines"], report["verdict"], report["low_confidence"]) == (1, "needs_check", True)
    assert report["skipped"] == [{"position": 2, "description": "Cv ketel onderhoud"}]
    assert len(report["lines"]) == 1


@pytest.mark.parametrize(
    ("qty", "shown"), [("10", "10"), ("100", "100"), ("2.5", "2.5"), ("0.5", "0.5"), ("2.000", "2")]
)
def test_report_quantity_is_fixed_point(qty: str, shown: str) -> None:
    (line,) = _report(_line(1, "131.00", qty=qty))["lines"]

    assert line["quantity"] == shown


def test_report_labels_each_line_decision_day_or_estimate() -> None:
    (line,) = _report(_line(1, "131.00"))["lines"]

    assert (line["reference_as_of"], line["snapshot_as_of"]) == ("decision_day", "2026-10-15")

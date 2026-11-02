"""Finance repository: rate cards, snapshot lookup by date, quotes once per source, company scoping."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.finance import PriceBasis, SnapshotBasis, Verdict
from app.core.errors import NotFoundError
from app.db.enums import QuoteSource, RateSource
from app.db.models import Company, QuoteLineRow, VendorRate
from app.finance import repo
from app.finance.stats import MarketStats
from tests.integration.finance_support import Seeded, action, seed_case

pytestmark = pytest.mark.integration
ITEM = "boiler_service"


def _stats(avg: str) -> MarketStats:
    value = Decimal(avg)
    return MarketStats(low=value, avg=value, high=value, n=3, trimmed=False, low_confidence=False)


def _snap(db: Session, seeded: Seeded, action_id: UUID, as_of: date, avg: str) -> None:
    assert repo.insert_snapshot(
        db, seeded.company_id, action_id=action_id, item_key=ITEM, unit="klus", as_of=as_of, stats=_stats(avg),
        basis=PriceBasis.fake, sources=[{"name": "fake", "price": avg, "observed_on": as_of.isoformat()}],
    )  # fmt: skip


def _upsert(db: Session, company_id: UUID, person_id: UUID, amount: str, unit: str = "uur") -> VendorRate:
    return repo.upsert_rate(
        db, company_id, person_id=person_id, item_key="leak_repair", description="Lekkage", unit=unit,
        amount=Decimal(amount), currency="eur", valid_from=date(2026, 1, 1), source=RateSource.owner,
    )  # fmt: skip


def test_snapshot_for_returns_the_latest_at_or_before_the_date(db: Session, company: Company) -> None:
    seeded = seed_case(db, company.id)
    later = action(db, company.id, seeded.case_id, seeded.vendor_id)
    _snap(db, seeded, seeded.action_id, date(2026, 10, 15), "100")
    _snap(db, seeded, later, date(2026, 10, 20), "130")

    def avg_on(on: date) -> Decimal | None:
        snap = repo.snapshot_for(db, company.id, seeded.case_id, ITEM, on)
        return snap.avg if snap else None

    assert avg_on(date(2026, 10, 15)) == Decimal(100)
    assert avg_on(date(2026, 10, 17)) == Decimal(100)
    assert avg_on(date(2026, 10, 30)) == Decimal(130)
    assert avg_on(date(2026, 10, 14)) is None  # only later snapshots exist
    assert [s.avg for s in repo.snapshots_for_case(db, company.id, seeded.case_id, date(2026, 10, 17))] == [100]
    assert repo.snapshot_for(db, new_company(db), seeded.case_id, ITEM, date(2026, 10, 30)) is None


def test_insert_snapshot_is_once_per_action_and_item_and_stores_the_unit_normalised(
    db: Session, company: Company
) -> None:
    seeded = seed_case(db, company.id)
    _snap(db, seeded, seeded.action_id, date(2026, 10, 15), "100")

    again = repo.insert_snapshot(
        db, company.id, action_id=seeded.action_id, item_key=ITEM, unit="job", as_of=date(2026, 10, 16),
        stats=_stats("999"), basis=PriceBasis.web, sources=[],
    )  # fmt: skip

    snap = repo.snapshot_for(db, company.id, seeded.case_id, ITEM, date(2026, 10, 31))
    assert again is False
    assert snap is not None
    assert (snap.unit, snap.avg) == ("job", Decimal(100))
    with pytest.raises(NotFoundError):  # an action of another company
        repo.insert_snapshot(
            db, new_company(db), action_id=seeded.action_id, item_key="x", unit="job", as_of=date(2026, 10, 15),
            stats=_stats("1"), basis=PriceBasis.fake, sources=[],
        )  # fmt: skip


def test_upsert_rate_replaces_the_same_version_and_current_rate_compares_units_normalised(
    db: Session, company: Company
) -> None:
    seeded = seed_case(db, company.id)
    _upsert(db, company.id, seeded.vendor_id, "60")
    updated = _upsert(db, company.id, seeded.vendor_id, "65", unit="hours")

    count = db.scalar(select(func.count(VendorRate.id)).where(VendorRate.company_id == company.id))
    found = repo.current_rate(db, company.id, seeded.vendor_id, "leak_repair", "uur", date(2026, 10, 15))
    assert count == 1
    assert (updated.amount, updated.unit, updated.currency) == (Decimal(65), "hour", "EUR")
    assert found is not None
    assert found.id == updated.id
    assert repo.current_rate(db, company.id, seeded.vendor_id, "leak_repair", "dag", date(2026, 10, 15)) is None
    assert repo.current_rate(db, company.id, seeded.vendor_id, "leak_repair", "uur", date(2025, 12, 31)) is None
    with pytest.raises(NotFoundError):  # the person is not this company's
        _upsert(db, new_company(db), seeded.vendor_id, "1")


def test_insert_quote_is_once_per_source_and_lines_and_reviews_are_scoped(db: Session, company: Company) -> None:
    seeded = seed_case(db, company.id)

    def quote(company_id: UUID) -> UUID | None:
        return repo.insert_quote(
            db, company_id, source=QuoteSource.message, source_id=seeded.message_id, quote_date=date(2026, 10, 30),
            currency="eur", case_id=seeded.case_id, person_id=seeded.vendor_id, total=Decimal("121.00"),
        )  # fmt: skip

    quote_id = quote(company.id)
    assert quote_id is not None
    assert quote(company.id) is None  # duplicate (company, source, source_id)
    line = repo.NewQuoteLine(
        position=1, description="Ketel", item_key=ITEM, quantity=Decimal(1), unit="klus", amount=Decimal(121)
    )
    (line_id,) = repo.insert_quote_lines(db, company.id, quote_id=quote_id, lines=[line])
    review_id = repo.insert_review(
        db, company.id, quote_id=quote_id, snapshot_basis=SnapshotBasis.decision_day, verdict=Verdict.ok,
        overcharge=Decimal(0), late_days=15, report={"lines": []},
    )  # fmt: skip
    stored = db.get(QuoteLineRow, line_id)
    assert stored is not None
    assert stored.unit == "job"
    assert review_id is not None
    other = new_company(db)
    with pytest.raises(NotFoundError):  # the message is not the other company's
        quote(other)
    with pytest.raises(NotFoundError):
        repo.insert_quote_lines(db, other, quote_id=quote_id, lines=[line])


def new_company(db: Session) -> UUID:
    other = Company(name="Other BV")
    db.add(other)
    db.flush()
    return other.id

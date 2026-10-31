"""CompetitorRatesSource reads other contractors' current agreed rates, scoped to one company."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.db.enums import PersonKind, RateSource
from app.db.models import Company, Person, VendorRate
from app.finance.competitors import CompetitorRatesSource

pytestmark = pytest.mark.integration
AS_OF = date(2026, 10, 31)
ITEM = "plumber_hourly"


def _person(s: Session, cid: UUID, name: str) -> UUID:
    p = Person(company_id=cid, kind=PersonKind.contractor, display_name=name, valid_from=date(2025, 1, 1))
    s.add(p)
    s.flush()
    return p.id


def _rate(
    s: Session,
    cid: UUID,
    pid: UUID,
    amount: str,
    *,
    unit: str = "hour",
    currency: str = "EUR",
    item: str = ITEM,
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
) -> None:
    s.add(
        VendorRate(
            company_id=cid,
            person_id=pid,
            item_key=item,
            description="d",
            unit=unit,
            amount=Decimal(amount),
            currency=currency,
            source=RateSource.owner,
            valid_from=valid_from,
            valid_to=valid_to,
        )
    )


def test_competitor_source_excludes_the_quoting_vendor_and_other_companies(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        other_company = Company(name="Other GmbH")
        s.add(other_company)
        s.flush()
        try:
            quoting = _person(s, cid, "Quoting BV")
            rival = _person(s, cid, "Rival BV")
            stranger = _person(s, other_company.id, "Stranger BV")
            _rate(s, cid, quoting, "99")
            _rate(s, cid, rival, "60")
            _rate(s, other_company.id, stranger, "10")
            s.commit()
            source = CompetitorRatesSource(_factory(migrated_engine), cid, quoting)
            got = source.lookup(ITEM, "hour", AS_OF)
        finally:
            s.rollback()
            from tests.integration.conftest import purge_company

            purge_company(migrated_engine, other_company.id)
    assert [(o.amount, o.source, o.url, o.vat_included, o.unit, o.observed_on) for o in got] == [
        (Decimal("60"), "competitor:Rival BV", None, False, "hour", AS_OF)
    ]


def test_competitor_source_honours_validity_dates_and_unit(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        a, b, c, d, e = (_person(s, cid, n) for n in ("Current", "Expired", "Future", "OtherUnit", "OtherItem"))
        _rate(s, cid, a, "50", valid_to=AS_OF)  # valid_to == as_of is still valid
        _rate(s, cid, b, "51", valid_to=date(2026, 10, 30))
        _rate(s, cid, c, "52", valid_from=date(2026, 11, 1))
        _rate(s, cid, d, "53", unit="piece")
        _rate(s, cid, e, "54", item="electrician_hourly")
        s.commit()
    got = CompetitorRatesSource(_factory(migrated_engine), cid, None).lookup(ITEM, "hour", AS_OF)
    assert [(o.amount, o.source) for o in got] == [(Decimal("50"), "competitor:Current")]


def test_competitor_source_ignores_non_reference_currency_and_includes_valid_from_today(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        eur, usd = _person(s, cid, "Euro"), _person(s, cid, "Dollar")
        _rate(s, cid, eur, "50", valid_from=AS_OF)  # valid_from == as_of is included
        _rate(s, cid, usd, "40", currency="USD")
        s.commit()
    got = CompetitorRatesSource(_factory(migrated_engine), cid, None).lookup(ITEM, "hour", AS_OF)
    assert [(o.amount, o.source) for o in got] == [(Decimal("50"), "competitor:Euro")]


def test_competitor_source_returns_one_observation_per_vendor_the_newest_version(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        vendor, other = _person(s, cid, "Versioned"), _person(s, cid, "Single")
        _rate(s, cid, vendor, "40", valid_from=date(2026, 1, 1))  # old, open-ended
        _rate(s, cid, vendor, "70", valid_from=date(2026, 6, 1), valid_to=date(2026, 12, 31))  # overlaps
        _rate(s, cid, other, "55")
        s.commit()
    got = CompetitorRatesSource(_factory(migrated_engine), cid, None).lookup(ITEM, "hour", AS_OF)
    assert [(o.amount, o.source) for o in got] == [
        (Decimal("55"), "competitor:Single"),
        (Decimal("70"), "competitor:Versioned"),
    ]


def test_competitor_source_ignores_a_rate_whose_person_belongs_to_another_company(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    with Session(migrated_engine) as s:
        other_company = Company(name="Foreign GmbH")
        s.add(other_company)
        s.flush()
        foreign_company_id = other_company.id
        try:
            foreign = _person(s, foreign_company_id, "Foreign BV")
            _rate(s, cid, foreign, "30")  # company differs from its person's company
            s.commit()
            got = CompetitorRatesSource(_factory(migrated_engine), cid, None).lookup(ITEM, "hour", AS_OF)
        finally:
            s.rollback()
            from tests.integration.conftest import purge_company

            s.execute(delete(VendorRate).where(VendorRate.company_id == cid))  # it references the foreign person
            s.commit()
            purge_company(migrated_engine, foreign_company_id)
    assert got == []


def _factory(engine: Engine) -> Callable[[], Session]:
    return lambda: Session(engine)

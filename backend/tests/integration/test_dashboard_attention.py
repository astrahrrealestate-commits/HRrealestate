"""The Today dashboard lists what BRIXX holds for the owner even with no Gmail or WhatsApp connected.

Synthetic rows only. Tickets come from the brixx mirror, rent from the ledger the mapper fills, leases from `leases`.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.api.dashboard.attention import Viewer, attention_items
from app.api.dashboard.routes import _brixx_sections
from app.db.models import Company, Lease, LeaseParty, Person, TenantRentPayment, Unit

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 5, 8, 9, 0, tzinfo=UTC)
OWNER = Viewer(money=True, inbox=True)


def _mirror(db: Session, table: str, company: Company, **values: Any) -> None:
    columns = ", ".join(["company_id", *values])
    binds = ", ".join(f":{name}" for name in ["company_id", *values])
    statement = f"insert into brixx.{table} ({columns}) values ({binds})"  # noqa: S608 - test table names
    db.execute(sa.text(statement), {"company_id": company.id, **values})


def _tenant(db: Session, company: Company, ref: str, name: str, unit_label: str) -> tuple[Person, Unit]:
    person = Person(company_id=company.id, kind="tenant", display_name=name, brixx_ref=ref, valid_from=TODAY)
    unit = Unit(company_id=company.id, label=unit_label, address=unit_label, brixx_ref=ref, valid_from=TODAY)
    db.add_all([person, unit])
    db.flush()
    return person, unit


def _lease(
    db: Session, company: Company, unit: Unit, person: Person, ends: date | None, brixx_ref: str | None = None
) -> Lease:
    lease = Lease(
        company_id=company.id,
        unit_id=unit.id,
        valid_from=date(2025, 1, 1),
        valid_to=ends,
        brixx_ref=brixx_ref or f"{unit.brixx_ref}:1",
    )
    db.add(lease)
    db.flush()
    db.add(LeaseParty(company_id=company.id, lease_id=lease.id, person_id=person.id, role="tenant"))
    return lease


def _rent(db: Session, company: Company, person: Person, unit: Unit, lease: Lease, **values: Any) -> None:
    defaults = {"invoice_number": "F-1", "billing_month": date(2026, 9, 1), "due_date": date(2026, 9, 5)}
    row = {"contract_rent_cents": 100000, "amount_paid_cents": 0, "status": "overdue", "overdue_days": 10, **defaults}
    db.add(
        TenantRentPayment(
            company_id=company.id, tenant_id=person.id, unit_id=unit.id, lease_id=lease.id, **{**row, **values}
        )
    )


@pytest.fixture
def seeded(db: Session, company: Company) -> Company:
    anna, unit_a = _tenant(db, company, "1", "Relatie R-00001", "Teststraat 1")
    bram, unit_b = _tenant(db, company, "2", "Relatie R-00002", "Teststraat 2")
    cor, unit_c = _tenant(db, company, "3", "Relatie R-00003", "Teststraat 3")
    lease_a = _lease(db, company, unit_a, anna, TODAY + timedelta(days=20))  # ends soon: urgent
    lease_b = _lease(db, company, unit_b, bram, TODAY + timedelta(days=80))  # ends later: listed, not urgent
    _lease(db, company, unit_c, cor, TODAY + timedelta(days=200))  # outside the window
    _rent(db, company, anna, unit_a, lease_a, overdue_days=70)  # urgent
    _rent(db, company, bram, unit_b, lease_b, overdue_days=10)  # not urgent
    _rent(
        db,
        company,
        cor,
        unit_c,
        _lease(db, company, unit_c, cor, None, brixx_ref="3:2"),
        status="paid",
        amount_paid_cents=100000,
    )
    base = {"prg_subobjectid": 1, "prg_relatieid": 1, "indverwijderd": 0, "newdatetime": NOW}
    _mirror(db, "tst_ticket", company, tst_ticketid=41, titel="Lekkage", indurgent=1, **base)
    _mirror(db, "tst_ticket", company, tst_ticketid=42, titel="Deurbel", **base)
    _mirror(db, "tst_ticket", company, tst_ticketid=43, titel="Klaar", datumgesloten=NOW, **base)
    return company


def test_open_brixx_tickets_overdue_rent_and_ending_leases_are_listed(db: Session, seeded: Company) -> None:
    items = attention_items(db, seeded.id, TODAY, OWNER)
    by_id = {i.id: i for i in items}
    assert {i.kind for i in items} == {"ticket", "rent", "lease"}
    assert sorted(i for i in by_id if i.startswith("brixx-")) == ["brixx-41", "brixx-42"]  # the closed one is not
    assert (by_id["brixx-41"].urgent, by_id["brixx-42"].urgent) == (True, False)
    assert by_id["brixx-41"].ageDays == (TODAY - NOW.date()).days
    rent = [i for i in items if i.kind == "rent"]
    assert sorted((i.partyName, i.urgent, i.ageDays) for i in rent) == [
        ("Relatie R-00001", True, 70),
        ("Relatie R-00002", False, 10),
    ]
    assert rent[0].title == "€1,000 rent overdue"
    leases = sorted((i.unitLabel, i.urgent, i.ageDays) for i in items if i.kind == "lease")
    assert leases == [("Teststraat 1", True, 20), ("Teststraat 2", False, 80)]


def test_urgent_items_come_first(db: Session, seeded: Company) -> None:
    flags = [i.urgent for i in attention_items(db, seeded.id, TODAY, OWNER)]
    assert flags == sorted(flags, reverse=True)


def test_nothing_from_another_company_is_listed(db: Session, seeded: Company) -> None:
    other = Company(name="Other BV")
    db.add(other)
    db.flush()
    assert attention_items(db, other.id, TODAY, OWNER) == []


def test_a_company_without_brixx_data_gets_no_items_and_no_sections(db: Session, company: Company) -> None:
    items = attention_items(db, company.id, TODAY, OWNER)
    assert items == []
    assert _brixx_sections(items) == []


def test_the_briefing_gets_one_section_per_kind(db: Session, seeded: Company) -> None:
    sections = {s.category: s for s in _brixx_sections(attention_items(db, seeded.id, TODAY, OWNER))}
    assert sorted(sections) == ["Leases ending soon (BRIXX)", "Open BRIXX tickets", "Rent arrears (BRIXX)"]
    assert sections["Open BRIXX tickets"].headline == "2 open tickets"
    assert sections["Rent arrears (BRIXX)"].headline == "2 tenants behind on rent"
    assert sections["Leases ending soon (BRIXX)"].headline == "2 leases ending within 90 days"
    assert sections["Open BRIXX tickets"].urgency == "high"


def _extra_lease(db: Session, company: Company, ends: date, label: str, ref: str) -> tuple[Lease, Unit]:
    person, unit = _tenant(db, company, ref, f"Relatie R-9{ref}", label)
    return _lease(db, company, unit, person, ends, brixx_ref=f"{ref}:1"), unit


def test_a_lease_with_two_tenants_is_one_item_and_the_boundaries_hold(db: Session, company: Company) -> None:
    lease, _ = _extra_lease(db, company, TODAY + timedelta(days=30), "Dubbelstraat 1", "11")  # exactly 30: urgent
    second = Person(company_id=company.id, kind="tenant", display_name="Relatie R-9x", brixx_ref="12", valid_from=TODAY)
    db.add(second)
    db.flush()
    db.add(LeaseParty(company_id=company.id, lease_id=lease.id, person_id=second.id, role="tenant"))
    _extra_lease(db, company, TODAY + timedelta(days=90), "Grensstraat 2", "13")  # exactly 90: listed
    _extra_lease(db, company, TODAY + timedelta(days=91), "Buitenstraat 3", "14")  # 91: not listed
    leases = sorted((i.unitLabel, i.urgent) for i in attention_items(db, company.id, TODAY, OWNER))
    assert leases == [("Dubbelstraat 1", True), ("Grensstraat 2", False)]


def test_rent_is_urgent_only_beyond_sixty_days_and_a_tenant_with_two_units_has_two_items(
    db: Session, company: Company
) -> None:
    person, unit_a = _tenant(db, company, "21", "Relatie R-00021", "Eerststraat 1")
    unit_b = Unit(
        company_id=company.id, label="Tweedestraat 2", address="Tweedestraat 2", brixx_ref="22", valid_from=TODAY
    )
    db.add(unit_b)
    db.flush()
    _rent(db, company, person, unit_a, _lease(db, company, unit_a, person, None), overdue_days=60)
    _rent(db, company, person, unit_b, _lease(db, company, unit_b, person, None), overdue_days=61)
    rent = {i.unitLabel: i for i in attention_items(db, company.id, TODAY, OWNER) if i.kind == "rent"}
    assert (rent["Eerststraat 1"].urgent, rent["Tweedestraat 2"].urgent) == (False, True)
    assert rent["Eerststraat 1"].id != rent["Tweedestraat 2"].id


def test_rent_and_leases_that_did_not_come_from_brixx_are_not_listed(db: Session, company: Company) -> None:
    person = Person(company_id=company.id, kind="tenant", display_name="Handmatig", valid_from=TODAY)
    unit = Unit(company_id=company.id, label="Eigenstraat 1", address="Eigenstraat 1", valid_from=TODAY)
    db.add_all([person, unit])
    db.flush()
    lease = Lease(company_id=company.id, unit_id=unit.id, valid_from=TODAY, valid_to=TODAY + timedelta(days=5))
    db.add(lease)
    db.flush()
    _rent(db, company, person, unit, lease, overdue_days=90)
    assert attention_items(db, company.id, TODAY, OWNER) == []


def test_a_dashboard_only_profile_sees_no_arrears_and_no_contact_data_as_names(db: Session, seeded: Company) -> None:
    db.execute(
        sa.update(Person)
        .where(Person.company_id == seeded.id, Person.brixx_ref == "1")
        .values(display_name="anna@example.test")
    )
    db.flush()
    items = attention_items(db, seeded.id, TODAY, Viewer(money=False, inbox=False))
    assert {i.kind for i in items} == {"ticket", "lease"}  # no rent
    text = " ".join(f"{i.partyName} {i.detail}" for i in items)
    assert "@" not in text
    assert "Unknown contact" in text

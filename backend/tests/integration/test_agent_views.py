"""The Super Agent's query tool sees what the dashboard shows: BRIXX tickets, rent, deposit and area.

Also keeps three lists in step: the views the allowlist permits, the views that exist in the database, and the views the
prompt tells the model about. Synthetic rows only.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.contracts import Category, Urgency
from app.db.models import Case, Company, Lease, LeaseParty, Person, Unit
from app.tools.query_agent.allowlist import ALLOWED_VIEWS
from app.tools.query_agent.prompt import QUERY_AGENT_SYSTEM_PROMPT

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


def _insert(db: Session, table: str, company: Company, **values: Any) -> None:
    columns = ", ".join(["company_id", *values])
    binds = ", ".join(f":{name}" for name in ["company_id", *values])
    statement = f"insert into brixx.{table} ({columns}) values ({binds})"  # noqa: S608 - test table names
    db.execute(sa.text(statement), {"company_id": company.id, **values})


@pytest.fixture
def seeded(db: Session, company: Company) -> Company:
    unit = Unit(
        company_id=company.id, label="Teststraat 5 A", address="Teststraat 5A", brixx_ref="100", valid_from=NOW.date()
    )
    tenant = Person(
        company_id=company.id, kind="tenant", display_name="Relatie R-00001", brixx_ref="1", valid_from=NOW.date()
    )
    plumber = Person(
        company_id=company.id, kind="contractor", display_name="Loodgieter BV", brixx_ref="3", valid_from=NOW.date()
    )
    db.add_all([unit, tenant, plumber])
    db.flush()
    lease = Lease(company_id=company.id, unit_id=unit.id, brixx_ref="500:900", valid_from=NOW.date())
    db.add(lease)
    db.flush()
    db.add(LeaseParty(company_id=company.id, lease_id=lease.id, person_id=tenant.id, role="tenant"))
    db.add(
        Case(
            company_id=company.id,
            unit_id=unit.id,
            primary_person_id=tenant.id,
            category=Category.maintenance,
            urgency=Urgency.normal,
            summary="Deur klemt",
        )
    )
    _insert(db, "typ_tickettype", company, typ_tickettypeid=1, benaming="Loodgieterswerk")
    base = {"prg_subobjectid": 100, "prg_relatieid": 1, "typ_tickettypeid": 1, "indverwijderd": 0}
    _insert(db, "tst_ticket", company, tst_ticketid=41, titel="Lekkage", dienstverlenerid=3, indurgent=1, **base)
    _insert(db, "tst_ticket", company, tst_ticketid=42, titel="Deurbel", datumgesloten=NOW, **base)
    _insert(db, "tst_ticket", company, tst_ticketid=43, titel="Oud", **{**base, "indverwijderd": 1})
    _insert(db, "tst_ticket", company, tst_ticketid=44, titel="Wist", **{**base, "prg_relatieid": 9})
    db.execute(
        sa.text("insert into brixx_erased_refs (id, company_id, relatie_id) values (:i, :c, 9)"),
        {"i": uuid.uuid4(), "c": company.id},
    )
    _insert(db, "prg_contract", company, prg_contractid=500, waarborgsom=3000)
    _insert(db, "prg_subobject", company, prg_subobjectid=100, vvo=62)
    _insert(db, "typ_huurcomponent", company, typ_huurcomponentid=1, benaming="Huur woonruimte")
    _insert(db, "typ_huurcomponent", company, typ_huurcomponentid=2, benaming="Servicekosten")
    line = {"prg_contractid": 500, "bedragex": 1500, "dm_bedragextermijnmnd": 1, "indverwijderd": 0}
    _insert(db, "fin_betaalregel", company, fin_betaalregelid=1, typ_huurcomponentid=1, **line)
    _insert(db, "fin_betaalregel", company, fin_betaalregelid=2, typ_huurcomponentid=2, **{**line, "bedragex": 120})
    return company


def _rows(db: Session, company: Company, sql: str) -> list[dict[str, Any]]:
    db.execute(sa.text("select set_config('app.company_id', :c, true)"), {"c": str(company.id)})
    return [dict(r) for r in db.execute(sa.text(sql)).mappings()]


def test_brixx_tickets_and_cases_are_one_list(db: Session, seeded: Company) -> None:
    rows = _rows(db, seeded, "select * from v_maintenance_tickets order by source, ticket_ref")
    brixx = {r["ticket_ref"]: r for r in rows if r["source"] == "brixx"}
    assert sorted(brixx) == ["BRIXX-41", "BRIXX-42"]  # the deleted and the erased person's tickets are not shown
    leak = brixx["BRIXX-41"]
    assert (leak["status"], leak["is_open"], leak["urgency"]) == ("dispatched", True, "high")
    assert (leak["unit_address"], leak["contractor_name"], leak["category"]) == (
        "Teststraat 5A",
        "Loodgieter BV",
        "Loodgieterswerk",
    )
    assert (brixx["BRIXX-42"]["status"], brixx["BRIXX-42"]["is_open"]) == ("completed", False)
    case_id = db.scalar(sa.text("select id from cases where company_id = :c"), {"c": seeded.id})
    own = [r for r in rows if r["source"] == "estateos"]
    assert [r["title"] for r in own] == ["Deur klemt"]
    assert own[0]["ticket_ref"] == "#" + str(case_id)[-6:]  # the owner-facing ref is the random tail, not the time head


def test_open_tickets_include_brixx(db: Session, seeded: Company) -> None:
    open_refs = _rows(db, seeded, "select ticket_ref from v_maintenance_tickets where is_open")
    assert {r["ticket_ref"] for r in open_refs} >= {"BRIXX-41"}
    assert "BRIXX-42" not in {r["ticket_ref"] for r in open_refs}


def test_lease_facts_give_rent_deposit_and_area(db: Session, seeded: Company) -> None:
    (row,) = _rows(db, seeded, "select * from v_lease_facts")
    assert (row["unit_address"], row["tenant_name"], row["is_active"]) == ("Teststraat 5A", "Relatie R-00001", True)
    assert (float(row["monthly_rent_eur"]), float(row["deposit_eur"]), row["living_area_sqm"]) == (1500.0, 3000.0, 62)


def test_views_show_nothing_of_another_company(db: Session, seeded: Company) -> None:
    other = Company(name="Other BV")
    db.add(other)
    db.flush()
    for view in ("v_maintenance_tickets", "v_lease_facts"):
        assert _rows(db, other, "select * from " + view) == []  # noqa: S608


def test_allowlist_database_and_prompt_agree_on_the_views(db: Session) -> None:
    existing = set(
        db.scalars(sa.text("select viewname from pg_views where schemaname = 'public' and viewname like 'v\\_%'"))
    )
    assert existing >= ALLOWED_VIEWS, f"allowed but not in the database: {sorted(ALLOWED_VIEWS - existing)}"
    assert not (existing - ALLOWED_VIEWS), f"in the database but not allowed: {sorted(existing - ALLOWED_VIEWS)}"
    assert not [v for v in ALLOWED_VIEWS if v not in QUERY_AGENT_SYSTEM_PROMPT], "a view the prompt never mentions"

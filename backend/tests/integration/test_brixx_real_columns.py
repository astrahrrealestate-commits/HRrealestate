"""The directory mapper and the maintenance feed against the column names the real hrrealestate BRIXX environment
sends (migration 0046's BRIXX_MIRROR), not the doc-example names: units are named by WEERGAVENAAM2 (not the numeric
VHENR), the tenant of a contract is EERSTERELATIEID / PRG_CONTRACTRELATIE (PRG_CONTRACT has no PRG_RELATIEID), and
TST_TICKET rows show up as maintenance tickets. Every value is invented.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.maintenance.brixx_tickets import brixx_tickets
from app.channels.brixx.models import BrixxField, BrixxTable
from app.db.enums import PersonKind
from app.db.models import Company, Lease, LeaseParty, Person, Unit
from app.directory.brixx.mapper import map_directory
from app.directory.brixx.upsert import upsert_page
from tests.integration.brixx_support import MirrorSchema, mirror_schema

pytestmark = pytest.mark.integration

TODAY = date(2026, 11, 16)
SYNCED = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
AUDIT = [
    ("VERSIENR", "BIGINT"),
    ("NEWDATETIME", "TIMESTAMP"),
    ("UPDDATETIME", "TIMESTAMP"),
    ("INDVERWIJDERD", "SMALLINT"),
]


def _info(name: str, pk: str, columns: list[tuple[str, str]]) -> BrixxTable:
    fields = [BrixxField(1, pk, "BIGINT", True, None, None)]
    fields += [BrixxField(i, c, kind, False, None, None) for i, (c, kind) in enumerate(columns, start=2)]
    return BrixxTable(name, pk, tuple(fields))


RELATIE = _info(
    "PRG_RELATIE", "PRG_RELATIEID", [("WEERGAVENAAM", "TEXT"), ("TELEFOON1", "TEXT"), ("EMAIL", "TEXT"), *AUDIT]
)
OBJECT = _info("PRG_OBJECT", "PRG_OBJECTID", [("OBJECTNR", "NUMERIC"), ("WEERGAVENAAM", "TEXT"), *AUDIT])
SUBOBJECT = _info(
    "PRG_SUBOBJECT",
    "PRG_SUBOBJECTID",
    [
        ("PRG_OBJECTID", "BIGINT"),
        ("VHENR", "NUMERIC"),
        ("SUBOBJECTNR", "NUMERIC"),
        ("WEERGAVENAAM", "TEXT"),
        ("WEERGAVENAAM2", "TEXT"),
        ("STRAATNM", "TEXT"),
        ("HUISNR", "INTEGER"),
        ("HUISLETTER", "TEXT"),
        ("POSTCODE", "TEXT"),
        ("WOONPLAATSNM", "TEXT"),
        ("VVO", "NUMERIC"),
        *AUDIT,
    ],
)
CONTRACT = _info(
    "PRG_CONTRACT",
    "PRG_CONTRACTID",
    [
        ("EERSTERELATIEID", "BIGINT"),
        ("CONTRACTNR", "NUMERIC"),
        ("INGANGSDATUM", "DATE"),
        ("EINDDATUM", "DATE"),
        ("WAARBORGSOM", "NUMERIC"),
        *AUDIT,
    ],
)
CONTRACTRELATIE = _info(
    "PRG_CONTRACTRELATIE",
    "PRG_CONTRACTRELATIEID",
    [("PRG_CONTRACTID", "BIGINT"), ("PRG_RELATIEID", "BIGINT"), ("VOLGNR", "NUMERIC"), *AUDIT],
)
CONTRACTVHE = _info(
    "PRG_CONTRACTVHE",
    "PRG_CONTRACTVHEID",
    [
        ("PRG_CONTRACTID", "BIGINT"),
        ("PRG_SUBOBJECTID", "BIGINT"),
        ("INGANGSDATUM", "DATE"),
        ("EINDDATUM", "DATE"),
        *AUDIT,
    ],
)
TICKET = _info(
    "TST_TICKET",
    "TST_TICKETID",
    [
        ("TITEL", "TEXT"),
        ("DMTICKETSTATUS", "TEXT"),
        ("INDURGENT", "SMALLINT"),
        ("DATUMGESLOTEN", "TIMESTAMP"),
        ("PRG_SUBOBJECTID", "BIGINT"),
        ("PRG_RELATIEID", "BIGINT"),
        ("DIENSTVERLENERID", "BIGINT"),
        ("TYP_TICKETTYPEID", "BIGINT"),
        ("TST_TICKET_LOCATIEID", "BIGINT"),
        *AUDIT,
    ],
)
TICKETTYPE = _info("TYP_TICKETTYPE", "TYP_TICKETTYPEID", [("BENAMING", "TEXT"), *AUDIT])
LOCATIE = _info("TST_TICKET_LOCATIE", "TST_TICKET_LOCATIEID", [("BENAMING", "TEXT"), *AUDIT])
BETAALREGEL = _info(
    "FIN_BETAALREGEL",
    "FIN_BETAALREGELID",
    [
        ("PRG_CONTRACTID", "BIGINT"),
        ("PRG_SUBOBJECTID", "BIGINT"),
        ("TYP_HUURCOMPONENTID", "BIGINT"),
        ("BEDRAGEX", "NUMERIC"),
        ("DM_BEDRAGEXTERMIJNMND", "NUMERIC"),
        ("INGANGSDATUM", "DATE"),
        ("EINDDATUM", "DATE"),
        *AUDIT,
    ],
)
HUURCOMPONENT = _info("TYP_HUURCOMPONENT", "TYP_HUURCOMPONENTID", [("BENAMING", "TEXT"), *AUDIT])
TABLES = (
    RELATIE,
    OBJECT,
    SUBOBJECT,
    CONTRACT,
    CONTRACTRELATIE,
    CONTRACTVHE,
    TICKET,
    TICKETTYPE,
    LOCATIE,
    BETAALREGEL,
    HUURCOMPONENT,
)


def _a(**row: object) -> dict[str, object]:
    return {"VERSIENR": 1, "NEWDATETIME": "2026-05-08T08:58:53", "UPDDATETIME": "2026-06-01T10:00:00",
            "INDVERWIJDERD": 0, **{k.upper(): v for k, v in row.items()}}  # fmt: skip


ROWS = {
    RELATIE.name: [
        _a(prg_relatieid=1, weergavenaam="Anna Testhuurder", telefoon1="06-12345678"),
        _a(prg_relatieid=2, weergavenaam="Bram Medehuurder"),
        _a(prg_relatieid=3, weergavenaam="Cees Loodgieter BV"),
        _a(prg_relatieid=4, weergavenaam="Dora Nobody"),
    ],
    OBJECT.name: [_a(prg_objectid=10, objectnr=Decimal(1), weergavenaam="00001 Teststraat 5 A")],
    SUBOBJECT.name: [
        _a(
            prg_subobjectid=100,
            prg_objectid=10,
            vhenr=Decimal("100000000100001.0"),
            subobjectnr=Decimal(1),
            weergavenaam="00001/001 Teststraat 5 A",
            weergavenaam2="Teststraat 5 A",
            straatnm="Teststraat",
            huisnr=5,
            huisletter="A",
            postcode="1000AA",
            woonplaatsnm="VOORBEELDSTAD",
            vvo=Decimal("62.5"),
        ),
    ],
    CONTRACT.name: [
        _a(prg_contractid=500, eersterelatieid=1, contractnr=Decimal(7), ingangsdatum="2026-02-01", waarborgsom=3000)
    ],
    HUURCOMPONENT.name: [
        _a(typ_huurcomponentid=1, benaming="Huur woonruimte"),
        _a(typ_huurcomponentid=2, benaming="Servicekosten"),
        _a(typ_huurcomponentid=3, benaming="Waarborg"),
        _a(typ_huurcomponentid=4, benaming="Huur parkeerplaats"),
    ],
    BETAALREGEL.name: [
        _a(
            fin_betaalregelid=1,
            prg_contractid=500,
            prg_subobjectid=100,
            typ_huurcomponentid=1,
            bedragex=1500,
            dm_bedragextermijnmnd=1,
            ingangsdatum="2026-02-01",
        ),
        _a(
            fin_betaalregelid=2,
            prg_contractid=500,
            prg_subobjectid=100,
            typ_huurcomponentid=4,
            bedragex=100,
            dm_bedragextermijnmnd=1,
            ingangsdatum="2026-02-01",
        ),
        _a(
            fin_betaalregelid=3,
            prg_contractid=500,
            prg_subobjectid=100,
            typ_huurcomponentid=2,
            bedragex=120,
            dm_bedragextermijnmnd=1,
            ingangsdatum="2026-02-01",
        ),
        _a(
            fin_betaalregelid=4,
            prg_contractid=500,
            prg_subobjectid=100,
            typ_huurcomponentid=3,
            bedragex=3000,
            ingangsdatum="2026-02-01",
        ),
        _a(
            fin_betaalregelid=5,
            prg_contractid=500,
            prg_subobjectid=100,
            typ_huurcomponentid=1,
            bedragex=1400,
            dm_bedragextermijnmnd=1,
            ingangsdatum="2025-01-01",
            einddatum="2026-01-31",
        ),
    ],
    CONTRACTRELATIE.name: [
        _a(prg_contractrelatieid=700, prg_contractid=500, prg_relatieid=1, volgnr=Decimal(1)),
        _a(prg_contractrelatieid=701, prg_contractid=500, prg_relatieid=2, volgnr=Decimal(2)),
    ],
    CONTRACTVHE.name: [_a(prg_contractvheid=900, prg_contractid=500, prg_subobjectid=100, ingangsdatum="2026-02-01")],
    TICKETTYPE.name: [_a(typ_tickettypeid=1, benaming="Ticket")],
    LOCATIE.name: [_a(tst_ticket_locatieid=1, benaming="Badkamer")],
    TICKET.name: [
        _a(
            tst_ticketid=41,
            titel="Lekkage onder de wastafel",
            dmticketstatus="AFWACHTING_DIENSTVERLENER",
            indurgent=1,
            prg_subobjectid=100,
            prg_relatieid=1,
            dienstverlenerid=3,
            typ_tickettypeid=1,
            tst_ticket_locatieid=1,
        ),
        _a(
            tst_ticketid=42,
            titel="Deurbel kapot",
            dmticketstatus="AFGEHANDELDDOORDIENSTVERLENER",
            indurgent=0,
            prg_subobjectid=100,
            prg_relatieid=1,
            typ_tickettypeid=1,
        ),
        _a(tst_ticketid=43, titel="Oude melding", dmticketstatus="NIEUW", indverwijderd=1, prg_subobjectid=100),
    ],
}


class Env:
    def __init__(self, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
        self.mirror, self.company_id = mirror, company_id
        self.tables = {info.name: mirror.create(info) for info in TABLES}
        with mirror.session() as s:
            for info in TABLES:
                upsert_page(s, self.tables[info.name], info, company_id, ROWS[info.name], SYNCED)
            s.commit()
        with mirror.session() as s:
            map_directory(s, company_id, TODAY)
            s.commit()

    def session(self) -> Session:
        return Session(self.mirror.engine, expire_on_commit=False)


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    with mirror_schema(migrated_engine) as mirror:
        yield Env(mirror, committed_company.id)


def test_units_are_named_by_their_brixx_display_name_not_their_number(env: Env) -> None:
    with env.session() as s:
        unit = s.scalars(sa.select(Unit).where(Unit.company_id == env.company_id)).one()
    assert unit.label == "Teststraat 5 A"
    assert unit.address == "Teststraat 5A, 1000AA VOORBEELDSTAD"


def test_contract_tenants_come_from_eersterelatieid_and_contractrelatie(env: Env) -> None:
    with env.session() as s:
        people = {p.brixx_ref: p for p in s.scalars(sa.select(Person).where(Person.company_id == env.company_id))}
        parties = set(
            s.execute(
                sa.select(Person.brixx_ref, LeaseParty.role)
                .join(LeaseParty, LeaseParty.person_id == Person.id)
                .join(Lease, Lease.id == LeaseParty.lease_id)
                .where(Lease.company_id == env.company_id)
            ).all()
        )
    assert (people["1"].kind, people["2"].kind) == (PersonKind.tenant, PersonKind.tenant)
    assert (people["3"].kind, people["4"].kind) == (PersonKind.other, PersonKind.other)
    assert parties == {("1", "tenant"), ("2", "co_tenant")}


def test_brixx_tickets_show_as_maintenance_tickets(env: Env) -> None:
    with env.session() as s:
        tickets = {t["id"]: t for t in brixx_tickets(s, env.company_id)}
    assert set(tickets) == {"brixx-41", "brixx-42"}  # the deleted one is not listed
    open_one = tickets["brixx-41"]
    assert (open_one["issueTitle"], open_one["unitLabel"], open_one["tenantName"]) == (
        "Lekkage onder de wastafel",
        "Teststraat 5 A",
        "Anna Testhuurder",
    )
    assert (open_one["status"], open_one["urgency"], open_one["contractorName"]) == (
        "dispatched",
        "high",
        "Cees Loodgieter BV",
    )
    assert open_one["category"] == "plumbing"
    assert open_one["ticketNumber"] == "BRIXX-41"
    assert tickets["brixx-42"]["status"] == "completed"


def test_brixx_tickets_are_tenant_scoped(env: Env) -> None:
    with env.session() as s:
        assert brixx_tickets(s, uuid.uuid4()) == []


def test_maintenance_api_lists_brixx_tickets_read_only(env: Env, pg_url: str) -> None:
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app.api.v1.auth import Principal
    from app.core.settings import Settings
    from app.main import create_app
    from tests.api_auth import as_owner

    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=env.company_id, owner_id=uuid.uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=env.mirror.engine, workflow_client=MagicMock()), owner)
    with TestClient(app) as client:
        listed = client.get("/api/maintenance/tickets").json()
        history = client.get("/api/maintenance/tickets/brixx-41/history")
        edit = client.patch(
            "/api/maintenance/tickets/brixx-41", json={"notes": "x"}, headers={"X-EstateOS-Client": "d"}
        )
        approve = client.post("/api/maintenance/tickets/brixx-41/approve", headers={"X-EstateOS-Client": "d"})
    ids = {t["id"]: t for t in listed["tickets"]}
    assert {"brixx-41", "brixx-42"} <= set(ids)
    assert ids["brixx-41"]["tenantName"] == "Anna Testhuurder"
    assert listed["stats"]["openCount"] >= 1
    assert history.status_code == 200
    assert history.json()["unitLabel"] == "Teststraat 5 A"
    assert (edit.status_code, approve.status_code) == (409, 409)


def test_a_new_case_lands_on_the_tenants_current_lease(env: Env) -> None:
    """One mapper run creates every lease with the same created_at: a tenant with an ended and a current contract
    must get new cases on the current unit, never an arbitrary one."""
    from app.contracts import Category, Urgency
    from app.pipeline.case_repo import create_case

    with env.session() as s:
        anna = s.scalars(sa.select(Person).where(Person.company_id == env.company_id, Person.brixx_ref == "1")).one()
        current = s.scalars(sa.select(Lease).where(Lease.company_id == env.company_id)).one()
        old_unit = Unit(company_id=env.company_id, label="Oude woning", valid_from=date(2020, 1, 1))
        s.add(old_unit)
        s.flush()
        ended = Lease(company_id=env.company_id, unit_id=old_unit.id, valid_from=date(2020, 1, 1),
                      valid_to=date(2025, 12, 31), created_at=current.created_at + timedelta(seconds=1))  # fmt: skip
        s.add(ended)
        s.flush()
        s.add(LeaseParty(company_id=env.company_id, lease_id=ended.id, person_id=anna.id, role="tenant"))
        s.flush()
        case_id = create_case(s, env.company_id, anna.id, Category.maintenance, Urgency.normal)
        from app.db.models import Case

        case = s.get(Case, case_id)
        assert case is not None
        assert (case.unit_id, case.lease_id) == (current.unit_id, current.id)
        s.rollback()


def test_an_erased_persons_brixx_tickets_are_not_shown(env: Env) -> None:
    from app.db.brixx_erasure import purge_brixx_relatie

    with env.session() as s:
        purge_brixx_relatie(s, env.company_id, 1)
        s.flush()
        assert brixx_tickets(s, env.company_id) == []  # both live tickets were Anna's
        s.rollback()


def test_properties_show_brixx_rent_area_and_deposit_never_invented(env: Env, pg_url: str) -> None:
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app.api.v1.auth import Principal
    from app.core.settings import Settings
    from app.main import create_app
    from tests.api_auth import as_owner

    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=env.company_id, owner_id=uuid.uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=env.mirror.engine, workflow_client=MagicMock()), owner)
    with TestClient(app) as client:
        units = client.get("/api/properties").json()["units"]
        tenants = client.get("/api/tenants").json()["tenants"]
    unit = units[0]
    assert (unit["label"], unit["currentTenant"], unit["status"]) == ("Teststraat 5 A", "Anna Testhuurder", "occupied")
    assert unit["monthlyRentEur"] == 1600.0  # current "Huur ..." lines only: no service costs, deposit or old rent
    assert (unit["livingAreaSqm"], unit["depositEur"], unit["floor"], unit["lockboxCode"]) == (62, 3000.0, None, None)
    anna = next(t for t in tenants if t["name"] == "Anna Testhuurder")
    assert (anna["unitLabel"], anna["monthlyRentEur"]) == ("Teststraat 5 A", 1600.0)


def test_contacts_carry_real_lease_facts_and_no_invented_rent_status(env: Env, pg_url: str) -> None:
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app.api.v1.auth import Principal
    from app.core.settings import Settings
    from app.main import create_app
    from tests.api_auth import as_owner

    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=env.company_id, owner_id=uuid.uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=env.mirror.engine, workflow_client=MagicMock()), owner)
    with TestClient(app) as client:
        contacts = client.get("/api/contacts", params={"audience": "tenant"}).json()
    anna = next(c for c in contacts if c["name"] == "Anna Testhuurder")
    assert (anna["monthlyRentEur"], anna["depositEur"]) == (1600.0, 3000.0)
    assert (anna["leaseStart"], anna["leaseEnd"]) == ("01-02-2026", None)  # open-ended
    assert anna["rentStatus"] == "unknown"  # no rent roll recorded: never "up to date" by default
    bram = next(c for c in contacts if c["name"] == "Bram Medehuurder")
    assert bram["unitRole"] == "Teststraat 5 A"  # a co-tenant has the tenancy too

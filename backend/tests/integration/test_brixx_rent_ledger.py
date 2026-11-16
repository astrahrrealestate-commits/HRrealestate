"""BRIXX invoices and payments -> the Money tab's rent ledger, and the "Relatie R-xxxx" fallback for the person names
BRIXX withholds. Column names are the real hrrealestate ones; every value is invented.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.models import BrixxField, BrixxTable
from app.db.models import Company, Person
from app.db.models.finance import MonthlyRentSummary, TenantRentPayment
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
    "PRG_RELATIE",
    "PRG_RELATIEID",
    [("RELATIENRSTR", "TEXT"), ("ORGANISATIENM", "TEXT"), ("ACHTERNAAM", "TEXT"), ("VOORNAAM", "TEXT"), *AUDIT],
)
SUBOBJECT = _info("PRG_SUBOBJECT", "PRG_SUBOBJECTID", [("WEERGAVENAAM2", "TEXT"), *AUDIT])
CONTRACT = _info("PRG_CONTRACT", "PRG_CONTRACTID", [("EERSTERELATIEID", "BIGINT"), ("INGANGSDATUM", "DATE"), *AUDIT])
CONTRACTVHE = _info(
    "PRG_CONTRACTVHE", "PRG_CONTRACTVHEID", [("PRG_CONTRACTID", "BIGINT"), ("PRG_SUBOBJECTID", "BIGINT"), *AUDIT]
)
FACTUUR = _info(
    "FIN_FACTUUR",
    "FIN_FACTUURID",
    [
        ("PRG_CONTRACTID", "BIGINT"),
        ("PLANDATUM", "DATE"),
        ("FACTUURNR", "TEXT"),
        ("FACTVERVALDATUM", "DATE"),
        ("DM_FACTUURSTATUS", "TEXT"),
        ("DM_FACTUURTYPE", "TEXT"),
        ("DM_BETALINGSTYPECODE", "TEXT"),
        ("TOTAALBEDRAGINCL", "NUMERIC"),
        *AUDIT,
    ],
)
BETALING = _info(
    "FIN_BETALING",
    "FIN_BETALINGID",
    [
        ("FIN_FACTUURID", "BIGINT"),
        ("BEDRAG", "NUMERIC"),
        ("STATUSDATUM", "DATE"),
        ("IND_GESTORNEERD", "SMALLINT"),
        *AUDIT,
    ],
)
TABLES = (RELATIE, SUBOBJECT, CONTRACT, CONTRACTVHE, FACTUUR, BETALING)


def _a(**row: object) -> dict[str, object]:
    return {"VERSIENR": 1, "NEWDATETIME": "2026-05-08T08:58:53", "UPDDATETIME": "2026-06-01T10:00:00",
            "INDVERWIJDERD": 0, **{k.upper(): v for k, v in row.items()}}  # fmt: skip


def _invoice(pk: int, plan: str, due: str, status: str, amount: int, number: str | None) -> dict[str, object]:
    return _a(
        fin_factuurid=pk, prg_contractid=500, plandatum=plan, factvervaldatum=due, dm_factuurstatus=status,
        dm_betalingstypecode="AUTOMATISCHE_INCASSO", totaalbedragincl=Decimal(amount), factuurnr=number,
    )  # fmt: skip


def _payment(pk: int, invoice: int, amount: int, day: str, *, reversed_: bool = False) -> dict[str, object]:
    return _a(
        fin_betalingid=pk, fin_factuurid=invoice, bedrag=Decimal(amount), statusdatum=day,
        ind_gestorneerd=int(reversed_),
    )  # fmt: skip


ROWS = {
    RELATIE.name: [
        _a(prg_relatieid=1, relatienrstr="R-00001"),
        _a(prg_relatieid=2, relatienrstr="R-00002", organisatienm="Voorbeeld Beheer B.V."),
    ],
    SUBOBJECT.name: [_a(prg_subobjectid=100, weergavenaam2="Teststraat 5 A")],
    CONTRACT.name: [_a(prg_contractid=500, eersterelatieid=1, ingangsdatum="2025-01-01")],
    CONTRACTVHE.name: [_a(prg_contractvheid=900, prg_contractid=500, prg_subobjectid=100)],
    FACTUUR.name: [
        _invoice(1, "2026-08-01", "2026-08-05", "DEFINITIEF", 1000, "F-1"),  # only a reversed payment: overdue
        _invoice(2, "2026-09-01", "2026-09-05", "DEFINITIEF", 1000, "F-2"),  # unpaid, due long ago: overdue
        _invoice(3, "2026-10-01", "2026-10-05", "DEFINITIEF", 1000, "F-3"),  # paid in full
        _invoice(4, "2026-11-01", "2026-11-25", "DEFINITIEF", 1000, "F-4"),  # half paid, not due yet: partial
        _invoice(5, "2026-12-01", "2026-12-05", "GEPLAND", 1000, None),  # next month: not in the ledger
    ],
    BETALING.name: [
        _payment(1, 1, 1000, "2026-08-04", reversed_=True),
        _payment(2, 3, 1000, "2026-10-03"),
        _payment(3, 4, 500, "2026-11-10"),
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
        self.map()

    def map(self) -> None:
        with self.mirror.session() as s:
            map_directory(s, self.company_id, TODAY)
            s.commit()

    def session(self) -> Session:
        return Session(self.mirror.engine, expire_on_commit=False)


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    with mirror_schema(migrated_engine) as mirror:
        yield Env(mirror, committed_company.id)


def _ledger(env: Env) -> dict[str, TenantRentPayment]:
    with env.session() as s:
        rows = s.scalars(sa.select(TenantRentPayment).where(TenantRentPayment.company_id == env.company_id))
        return {f"{r.billing_month:%Y-%m}": r for r in rows}


def test_ledger_status_follows_invoices_and_payments(env: Env) -> None:
    ledger = _ledger(env)
    assert sorted(ledger) == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert [ledger[m].status for m in sorted(ledger)] == ["overdue", "overdue", "paid", "partial"]
    assert ledger["2026-08"].amount_paid_cents == 0  # the reversed payment does not count
    assert (ledger["2026-09"].overdue_days, ledger["2026-09"].invoice_number) == (72, "F-2")
    assert (ledger["2026-10"].contract_rent_cents, ledger["2026-10"].amount_paid_cents) == (100000, 100000)
    paid_at = ledger["2026-10"].paid_at
    assert paid_at is not None
    assert paid_at.date() == date(2026, 10, 3)
    assert (ledger["2026-11"].amount_paid_cents, ledger["2026-11"].due_date) == (50000, date(2026, 11, 25))
    assert ledger["2026-10"].payment_method == "SEPA direct debit"


def test_summaries_roll_up_the_ledger(env: Env) -> None:
    with env.session() as s:
        rows = s.scalars(sa.select(MonthlyRentSummary).where(MonthlyRentSummary.company_id == env.company_id))
        by_month = {f"{r.billing_month:%Y-%m}": r for r in rows}
    assert sorted(by_month) == ["2026-08", "2026-09", "2026-10", "2026-11"]
    sept, nov = by_month["2026-09"], by_month["2026-11"]
    assert (sept.total_overdue_rent_cents, sept.overdue_tenants_count, sept.collection_rate_pct) == (100000, 1, 0)
    assert (nov.total_collected_rent_cents, nov.collection_rate_pct, nov.paid_tenants_count) == (50000, 50, 0)


def test_second_run_changes_nothing_and_a_payment_updates_the_row(env: Env) -> None:
    before = {m: row.id for m, row in _ledger(env).items()}
    env.map()
    assert {m: row.id for m, row in _ledger(env).items()} == before
    with env.mirror.session() as s:
        page = [_payment(4, 2, 1000, "2026-11-12")]
        upsert_page(s, env.tables[BETALING.name], BETALING, env.company_id, page, SYNCED)
        s.commit()
    env.map()
    sept = _ledger(env)["2026-09"]
    assert (sept.status, sept.amount_paid_cents, sept.overdue_days) == ("paid", 100000, 0)


def test_person_names_brixx_withholds_fall_back_to_the_relatie_number(env: Env) -> None:
    with env.session() as s:
        names = {
            p.brixx_ref: p.display_name for p in s.scalars(sa.select(Person).where(Person.company_id == env.company_id))
        }
    assert names == {"1": "Relatie R-00001", "2": "Voorbeeld Beheer B.V."}


def test_a_real_name_replaces_the_generated_label_but_a_manual_rename_survives(env: Env) -> None:
    with env.session() as s:
        s.execute(sa.update(Person).where(Person.brixx_ref == "2").values(display_name="Renamed by owner"))
        s.commit()
    with env.mirror.session() as s:
        page = [
            _a(prg_relatieid=1, relatienrstr="R-00001", voornaam="Jan", achternaam="Jansen"),
            _a(prg_relatieid=2, relatienrstr="R-00002"),
        ]
        upsert_page(s, env.tables[RELATIE.name], RELATIE, env.company_id, page, SYNCED)
        s.commit()
    env.map()
    with env.session() as s:
        names = {
            p.brixx_ref: p.display_name for p in s.scalars(sa.select(Person).where(Person.company_id == env.company_id))
        }
    assert names == {"1": "Jan Jansen", "2": "Renamed by owner"}


def test_a_planned_credit_is_not_billed_until_it_is_issued(env: Env) -> None:
    credit = {**_invoice(10, "2026-11-01", "2026-11-25", "GEPLAND", -200, None), "DM_FACTUURTYPE": "CREDIT"}
    _put(env, FACTUUR, [credit])
    env.map()
    assert (_ledger(env)["2026-11"].contract_rent_cents, _ledger(env)["2026-11"].status) == (100000, "partial")
    _put(env, FACTUUR, [{**credit, "DM_FACTUURSTATUS": "DEFINITIEF"}])
    env.map()
    assert _ledger(env)["2026-11"].contract_rent_cents == 80000


def _put(env: Env, info: BrixxTable, rows: list[dict[str, object]]) -> None:
    with env.mirror.session() as s:
        upsert_page(s, env.tables[info.name], info, env.company_id, rows, SYNCED)
        s.commit()


def test_deleted_payment_does_not_count_and_credit_and_second_invoice_net_into_the_month(env: Env) -> None:
    _put(env, BETALING, [{**_payment(2, 3, 1000, "2026-10-03"), "INDVERWIJDERD": 1}])
    _put(
        env,
        FACTUUR,
        [
            _invoice(6, "2026-10-01", "2026-10-05", "DEFINITIEF", 200, "F-6"),
            _invoice(7, "2026-10-01", "2026-10-05", "DEFINITIEF", -50, "F-7"),
        ],
    )
    env.map()
    october = _ledger(env)["2026-10"]
    assert (october.contract_rent_cents, october.amount_paid_cents) == (115000, 0)
    assert (october.status, october.invoice_number) == ("overdue", "F-3")


def test_planned_only_month_has_a_placeholder_number_and_is_never_overdue(env: Env) -> None:
    _put(env, FACTUUR, [_invoice(8, "2026-11-01", "2026-11-02", "GEPLAND", 700, None)])
    _put(env, FACTUUR, [_invoice(4, "2026-11-01", "2026-11-25", "GEPLAND", 1000, None)])
    _put(env, BETALING, [{**_payment(3, 4, 500, "2026-11-10"), "INDVERWIJDERD": 1}])
    env.map()
    november = _ledger(env)["2026-11"]
    assert (november.status, november.contract_rent_cents, november.invoice_number) == (
        "pending",
        170000,
        "PLAN-500-202611",
    )


def test_rows_of_invoices_that_left_the_mirror_are_removed_but_an_empty_mirror_prunes_nothing(env: Env) -> None:
    with env.mirror.session() as s:
        s.execute(sa.delete(env.tables[FACTUUR.name]).where(env.tables[FACTUUR.name].c.fin_factuurid == 1))
        s.commit()
    env.map()
    assert sorted(_ledger(env)) == ["2026-09", "2026-10", "2026-11"]
    with env.mirror.session() as s:
        s.execute(sa.delete(env.tables[FACTUUR.name]))
        s.commit()
    env.map()
    assert sorted(_ledger(env)) == ["2026-09", "2026-10", "2026-11"]


def test_a_contract_whose_lease_has_no_tenant_gets_no_ledger_row(env: Env) -> None:
    _put(env, FACTUUR, [{**_invoice(9, "2026-11-01", "2026-11-25", "DEFINITIEF", 900, "F-9"), "PRG_CONTRACTID": 777}])
    env.map()
    assert sorted(_ledger(env)) == ["2026-08", "2026-09", "2026-10", "2026-11"]

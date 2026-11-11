"""Idempotent seed script for Tenant Rent Ledger & Monthly Collections Summaries."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.db.enums import PersonKind
from app.db.models import Company, Lease, LeaseParty, MonthlyRentSummary, Person, TenantRentPayment, Unit

PRIMARY_COMPANY_ID = UUID("01a1341b-2e4e-7073-b44e-40a7bc9e8e2a")

PORTFOLIO_TENANTS = [
    {
        "name": "Vipin Tyagi",
        "email": "vipint9902@gmail.com",
        "phone": "+31 6 94 56 16 99",
        "unit": "Keizersgracht 42-A",
        "address": "Keizersgracht 42-A, 1015 CS Amsterdam",
        "rent_eur": 1850.0,
        "nov_status": "overdue",
        "nov_overdue_days": 10,
        "notes": "Payment reversed: reported kitchen leak pending inspection.",
    },
    {
        "name": "Lars van den Berg",
        "email": "lars.vandenberg@example.nl",
        "phone": "+31 6 44 22 88 19",
        "unit": "Henry Dunantweg 5 F",
        "address": "Henry Dunantweg 5 F, 1066 AX Amsterdam",
        "rent_eur": 1390.0,
        "nov_status": "overdue",
        "nov_overdue_days": 10,
        "notes": "Move-out agreed for year-end; arrears payment plan established.",
    },
    {
        "name": "Pieter Bakker",
        "email": "pieter.bakker@example.nl",
        "phone": "+31 6 12 34 56 78",
        "unit": "Pieter Floriszstraat 1 C",
        "address": "Pieter Floriszstraat 1 C, 1052 BA Amsterdam",
        "rent_eur": 1450.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "09:12:00",
        "notes": "Direct Debit SEPA batch settled on time.",
    },
    {
        "name": "Marloes Jansen",
        "email": "marloes.jansen@example.nl",
        "phone": "+31 6 22 33 44 55",
        "unit": "Singel 412",
        "address": "Singel 412, 1016 AK Amsterdam",
        "rent_eur": 2200.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "08:45:10",
        "notes": "Cleared via automated SEPA mandate.",
    },
    {
        "name": "Anouk de Jong",
        "email": "anouk.dejong@example.nl",
        "phone": "+31 6 33 44 55 66",
        "unit": "Keizersgracht 42-B",
        "address": "Keizersgracht 42-B, 1015 CS Amsterdam",
        "rent_eur": 2450.0,
        "nov_status": "paid",
        "nov_paid_day": 2,
        "nov_paid_time": "11:20:30",
        "notes": "Bank transfer received.",
    },
    {
        "name": "Daan Vermeulen",
        "email": "daan.vermeulen@example.nl",
        "phone": "+31 6 55 66 77 88",
        "unit": "Prinses Marijkestraat 2 A",
        "address": "Prinses Marijkestraat 2 A, 1077 XA Amsterdam",
        "rent_eur": 1850.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "14:02:15",
        "notes": "Cleared via SEPA direct debit.",
    },
    {
        "name": "Elena Rostova",
        "email": "elena.rostova@example.nl",
        "phone": "+31 6 77 88 99 00",
        "unit": "Keizersgracht 42-C",
        "address": "Keizersgracht 42-C, 1015 CS Amsterdam",
        "rent_eur": 2650.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "07:30:00",
        "notes": "Direct debit settled on time.",
    },
    {
        "name": "Sanne de Vries",
        "email": "sanne.devries@example.nl",
        "phone": "+31 6 88 99 00 11",
        "unit": "Prinsengracht 118-B",
        "address": "Prinsengracht 118-B, 1015 EA Amsterdam",
        "rent_eur": 1950.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "10:15:00",
        "notes": "Direct debit settled on time.",
    },
    {
        "name": "Mohammed El Amrani",
        "email": "mohammed.elamrani@example.nl",
        "phone": "+31 6 99 00 11 22",
        "unit": "Lijnbaansgracht 9-C",
        "address": "Lijnbaansgracht 9-C, 1017 PN Amsterdam",
        "rent_eur": 2100.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "09:50:00",
        "notes": "SEPA Direct debit settled.",
    },
    {
        "name": "Lotte Jansen",
        "email": "lotte.jansen@example.nl",
        "phone": "+31 6 11 22 33 44",
        "unit": "Dorpsstraat 54 E",
        "address": "Dorpsstraat 54 E, 1182 JG Amstelveen",
        "rent_eur": 1750.0,
        "nov_status": "paid",
        "nov_paid_day": 1,
        "nov_paid_time": "12:10:00",
        "notes": "Direct debit settled on time.",
    },
]


def seed_rent_data() -> None:
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_url)

    with Session(engine) as session, session.begin():
        company = session.get(Company, PRIMARY_COMPANY_ID)
        if not company:
            print(f"Company {PRIMARY_COMPANY_ID} not found.")
            return

        print(f"Seeding tenant rent records for company: {company.name} ({PRIMARY_COMPANY_ID})")

        # 1. Seed or retrieve Unit, Person, and Lease for each tenant
        for item in PORTFOLIO_TENANTS:
            # Unit
            unit = session.scalars(
                select(Unit).where(Unit.company_id == PRIMARY_COMPANY_ID, Unit.label == item["unit"])
            ).first()
            if not unit:
                unit = Unit(
                    id=uuid4(),
                    company_id=PRIMARY_COMPANY_ID,
                    label=item["unit"],
                    address=item["address"],
                    valid_from=date(2025, 1, 1),
                )
                session.add(unit)
                session.flush()

            # Person (Tenant)
            person = session.scalars(
                select(Person).where(
                    Person.company_id == PRIMARY_COMPANY_ID,
                    Person.display_name == item["name"],
                )
            ).first()
            if not person:
                person = Person(
                    id=uuid4(),
                    company_id=PRIMARY_COMPANY_ID,
                    kind=PersonKind.tenant,
                    display_name=item["name"],
                    valid_from=date(2025, 1, 1),
                )
                session.add(person)
                session.flush()

            # Lease
            lease = session.scalars(
                select(Lease).where(Lease.company_id == PRIMARY_COMPANY_ID, Lease.unit_id == unit.id)
            ).first()
            if not lease:
                lease = Lease(
                    id=uuid4(),
                    company_id=PRIMARY_COMPANY_ID,
                    unit_id=unit.id,
                    valid_from=date(2025, 1, 1),
                )
                session.add(lease)
                session.flush()
                # Attach LeaseParty
                lp = LeaseParty(
                    company_id=PRIMARY_COMPANY_ID,
                    lease_id=lease.id,
                    person_id=person.id,
                    role="tenant",
                )
                session.add(lp)
                session.flush()

            rent_cents = int(item["rent_eur"] * 100)

            # 2. Seed Monthly Rent Payments for September, October, and November 2026
            cycles = [
                (date(2026, 9, 1), "paid", 0, date(2026, 9, 1), datetime(2026, 9, 1, 9, 0, tzinfo=UTC)),
                (date(2026, 10, 1), "paid", 0, date(2026, 10, 1), datetime(2026, 10, 1, 9, 0, tzinfo=UTC)),
                (
                    date(2026, 11, 1),
                    item["nov_status"],
                    item.get("nov_overdue_days", 0),
                    date(2026, 11, 1),
                    datetime.combine(
                        date(2026, 11, item.get("nov_paid_day", 1)),
                        time.fromisoformat(item.get("nov_paid_time", "09:00:00")),
                        tzinfo=UTC,
                    )
                    if item["nov_status"] == "paid"
                    else None,
                ),
            ]

            for billing_month, status, overdue_days, due_date, paid_at in cycles:
                existing_tx = session.scalars(
                    select(TenantRentPayment).where(
                        TenantRentPayment.company_id == PRIMARY_COMPANY_ID,
                        TenantRentPayment.lease_id == lease.id,
                        TenantRentPayment.billing_month == billing_month,
                    )
                ).first()

                inv_num = f"RENT-{billing_month.year}-{billing_month.month:02d}-{str(lease.id)[:4].upper()}"
                amt_paid = rent_cents if status == "paid" else 0

                if not existing_tx:
                    tx = TenantRentPayment(
                        id=uuid4(),
                        company_id=PRIMARY_COMPANY_ID,
                        invoice_number=inv_num,
                        tenant_id=person.id,
                        unit_id=unit.id,
                        lease_id=lease.id,
                        billing_month=billing_month,
                        contract_rent_cents=rent_cents,
                        amount_paid_cents=amt_paid,
                        due_date=due_date,
                        paid_at=paid_at,
                        status=status,
                        overdue_days=overdue_days,
                        payment_method="SEPA Direct Debit",
                        transaction_reference=f"SEPA-NL2026-{uuid4().hex[:8].upper()}" if status == "paid" else None,
                        notes=item.get("notes") if billing_month == date(2026, 11, 1) else "Settled on time.",
                    )
                    session.add(tx)
                else:
                    existing_tx.status = status
                    existing_tx.overdue_days = overdue_days
                    existing_tx.paid_at = paid_at
                    existing_tx.amount_paid_cents = amt_paid

        # 3. Seed Monthly Rent Summaries (June through November 2026) for MoM Comparison & Charting
        summaries = [
            (date(2026, 6, 1), 16200000, 16200000, 0, 104, 104, 0, Decimal("100.0")),
            (date(2026, 7, 1), 16350000, 16350000, 0, 106, 106, 0, Decimal("100.0")),
            (date(2026, 8, 1), 16400000, 16400000, 0, 107, 107, 0, Decimal("100.0")),
            (date(2026, 9, 1), 16500000, 16315000, 185000, 108, 107, 1, Decimal("98.8")),
            (date(2026, 10, 1), 16573400, 16573400, 0, 110, 110, 0, Decimal("100.0")),
            (date(2026, 11, 1), 16573400, 16249400, 324000, 110, 108, 2, Decimal("98.0")),
        ]

        for b_month, sched, coll, overdue, tot_t, paid_t, overdue_t, rate in summaries:
            s_row = session.scalars(
                select(MonthlyRentSummary).where(
                    MonthlyRentSummary.company_id == PRIMARY_COMPANY_ID,
                    MonthlyRentSummary.billing_month == b_month,
                )
            ).first()

            if not s_row:
                s_row = MonthlyRentSummary(
                    id=uuid4(),
                    company_id=PRIMARY_COMPANY_ID,
                    billing_month=b_month,
                    total_scheduled_rent_cents=sched,
                    total_collected_rent_cents=coll,
                    total_overdue_rent_cents=overdue,
                    total_tenants_count=tot_t,
                    paid_tenants_count=paid_t,
                    overdue_tenants_count=overdue_t,
                    collection_rate_pct=rate,
                )
                session.add(s_row)
            else:
                s_row.total_scheduled_rent_cents = sched
                s_row.total_collected_rent_cents = coll
                s_row.total_overdue_rent_cents = overdue
                s_row.total_tenants_count = tot_t
                s_row.paid_tenants_count = paid_t
                s_row.overdue_tenants_count = overdue_t
                s_row.collection_rate_pct = rate

    print("\n[+] Tenant rent payments and monthly summaries successfully seeded into PostgreSQL!")


if __name__ == "__main__":
    seed_rent_data()


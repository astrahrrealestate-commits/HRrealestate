"""`FIN_FACTUUR` + `FIN_BETALING` -> `tenant_rent_payments` + `monthly_rent_summaries` (the Money tab).

One ledger row per lease and billing month (`PLANDATUM`'s month), up to and including the current month. A contract's
invoices of that month are summed (credit and correction invoices carry negative amounts); payments are the contract
invoices' `FIN_BETALING` rows that were not reversed (`IND_GESTORNEERD`). `GEPLAND` invoices are planned and not yet
issued: pending, never overdue; planned credits and corrections (`DM_FACTUURTYPE` other than `NORMAAL`) are left out
until issued. An issued (`DEFINITIEF`) invoice past its due date and not fully paid is overdue. Invoices of contracts
BRIXX no longer lists (stage: 22 old contracts, last billed 2026-05) have no lease or tenant and are skipped.
The ledger amount is the invoiced total incl. VAT, so service costs billed on the same invoice are included.
A contract with several unit links books its invoices on the first link (lowest contract-VHE id). Rows for leases
BRIXX no longer invoices are removed; rows of leases without a mapped tenant are skipped. Flushes; the caller commits.
"""

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Lease, LeaseParty
from app.db.models.finance import MonthlyRentSummary, TenantRentPayment
from app.directory.brixx import columns as col
from app.directory.brixx.map_common import MapCounts, changed, lock_company

INVOICE_PK, PAYMENT_PK = "fin_factuurid", "fin_betalingid"
INVOICE, PAYMENT = "fin_factuur", "fin_betaling"
PLANNED = "gepland"
_CENT = Decimal("0.01")


@dataclass
class _Month:
    """The invoices of one contract in one billing month, summed."""

    numbers: list[str] = field(default_factory=list)
    total: Decimal = Decimal(0)
    paid: Decimal = Decimal(0)
    due: date | None = None
    issued_due: date | None = None  # earliest due date of an issued invoice
    last_paid: date | None = None
    method: str | None = None


@dataclass(frozen=True)
class _Holder:
    lease_id: UUID
    unit_id: UUID
    tenant_id: UUID


def _money(value: object) -> Decimal:
    return (
        Decimal(str(value)).quantize(_CENT, ROUND_HALF_UP) if isinstance(value, int | float | Decimal) else Decimal(0)
    )


def _cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value(ROUND_HALF_UP))


def method_label(code: object) -> str:
    """A readable payment method from `DM_BETALINGSTYPECODE` ("AUTOMATISCHE_INCASSO" -> "SEPA direct debit")."""
    text = str(code or "").strip().upper()
    if not text:
        return "Bank transfer"
    return "SEPA direct debit" if "INCASSO" in text else text.replace("_", " ").capitalize()


def holders(session: Session, company_id: UUID) -> dict[int, _Holder]:
    """Per contract id: the first lease (lowest link id) with a mapped tenant party."""
    rows = session.execute(
        sa.select(Lease.brixx_ref, Lease.id, Lease.unit_id, LeaseParty.person_id)
        .join(LeaseParty, sa.and_(LeaseParty.lease_id == Lease.id, LeaseParty.role == "tenant"))
        .where(Lease.company_id == company_id, Lease.brixx_ref.is_not(None))
    )
    best: dict[int, tuple[int, _Holder]] = {}
    for ref, lease_id, unit_id, tenant_id in rows:
        contract, _, link = str(ref).partition(":")
        key, order = col.as_int(contract), col.as_int(link) or 0
        if key is not None and (key not in best or order < best[key][0]):
            best[key] = (order, _Holder(lease_id, unit_id, tenant_id))
    return {key: holder for key, (_, holder) in best.items()}


def _payments(rows: Sequence[col.Row]) -> dict[int, tuple[Decimal, date | None]]:
    """Per invoice id: (sum of non-reversed payments, date of the latest one)."""
    paid: dict[int, tuple[Decimal, date | None]] = {}
    for row in rows:
        invoice = col.pick_int(row, (INVOICE_PK,))
        if invoice is None or col.is_ended(row) or col.is_flagged(row, "ind_gestorneerd"):
            continue
        total, last = paid.get(invoice, (Decimal(0), None))
        day = col.pick_date(row, ("statusdatum",))
        paid[invoice] = (total + _money(row.get("bedrag")), max(filter(None, (last, day)), default=None))
    return paid


def _planned_adjustment(row: col.Row) -> bool:
    """A planned credit or correction: BRIXX has not issued it, so it is neither billed nor due."""
    kind = str(row.get("dm_factuurtype") or "").lower()
    return str(row.get("dm_factuurstatus") or "").lower() == PLANNED and kind not in ("", "normaal")


def _collect(
    invoices: Sequence[col.Row], payments: dict[int, tuple[Decimal, date | None]], today: date
) -> dict[tuple[int, date], _Month]:
    months: dict[tuple[int, date], _Month] = defaultdict(_Month)
    for row in invoices:
        contract, planned = col.pick_int(row, (col.CONTRACT_PK,)), col.pick_date(row, ("plandatum",))
        if contract is None or planned is None or col.is_ended(row) or _planned_adjustment(row):
            continue
        first = planned.replace(day=1)
        if first > today.replace(day=1):
            continue
        month = months[(contract, first)]
        paid, last = payments.get(col.pick_int(row, (INVOICE_PK,)) or -1, (Decimal(0), None))
        due = col.pick_date(row, ("factvervaldatum",)) or planned
        month.total += _money(row.get("totaalbedragincl"))
        month.paid += paid
        month.due = min(filter(None, (month.due, due)))
        month.last_paid = max(filter(None, (month.last_paid, last)), default=None)
        month.method = month.method or method_label(row.get("dm_betalingstypecode"))
        if str(row.get("dm_factuurstatus") or "").lower() != PLANNED:
            month.issued_due = min(filter(None, (month.issued_due, due)))
        if number := col.pick_text(row, ("factuurnr",), 64):
            month.numbers.append(number)
    return months


def status_of(month: _Month, today: date) -> tuple[str, int]:
    """(`paid` | `partial` | `overdue` | `pending`, days overdue)."""
    if month.total <= 0 or month.paid >= month.total:
        return "paid", 0
    if month.issued_due is not None and month.issued_due < today:
        return "overdue", (today - month.issued_due).days
    return ("partial" if month.paid > 0 else "pending"), 0


def _values(contract: int, first: date, month: _Month, holder: _Holder, today: date) -> dict[str, object]:
    status, days = status_of(month, today)
    paid_at = (
        datetime.combine(month.last_paid, datetime.min.time(), tzinfo=UTC)
        if status == "paid" and month.last_paid
        else None
    )
    return {
        "invoice_number": (sorted(month.numbers)[0] if month.numbers else f"PLAN-{contract}-{first:%Y%m}")[:64],
        "tenant_id": holder.tenant_id,
        "unit_id": holder.unit_id,
        "contract_rent_cents": _cents(month.total),
        "amount_paid_cents": _cents(month.paid),
        "due_date": month.due or first,
        "paid_at": paid_at,
        "status": status,
        "overdue_days": days,
        "payment_method": month.method or "Bank transfer",
    }


def _upsert(
    session: Session, company_id: UUID, wanted: dict[tuple[UUID, date], dict[str, object]], *, prune: bool
) -> Counter[str]:
    existing = {
        (r.lease_id, r.billing_month): r
        for r in session.scalars(sa.select(TenantRentPayment).where(TenantRentPayment.company_id == company_id))
    }
    outcomes: Counter[str] = Counter()
    for key, values in wanted.items():
        row = existing.pop(key, None)
        if row is None:
            session.add(TenantRentPayment(company_id=company_id, lease_id=key[0], billing_month=key[1], **values))
            outcomes["created"] += 1
        else:
            outcomes["updated" if changed(row, **values) else "unchanged"] += 1
    if prune:
        derived = set(
            session.scalars(sa.select(Lease.id).where(Lease.company_id == company_id, Lease.brixx_ref.is_not(None)))
        )
        for stale in existing.values():
            if stale.lease_id in derived:
                session.delete(stale)
    return outcomes


def _summarise(
    session: Session, company_id: UUID, wanted: dict[tuple[UUID, date], dict[str, object]], *, prune: bool
) -> None:
    by_month: dict[date, list[dict[str, object]]] = defaultdict(list)
    for (_, first), values in wanted.items():
        by_month[first].append(values)
    existing = {
        s.billing_month: s
        for s in session.scalars(sa.select(MonthlyRentSummary).where(MonthlyRentSummary.company_id == company_id))
    }
    for first, rows in by_month.items():
        scheduled = sum(int(str(r["contract_rent_cents"])) for r in rows)
        collected = sum(int(str(r["amount_paid_cents"])) for r in rows)
        overdue = [r for r in rows if r["status"] == "overdue"]
        values = {
            "total_scheduled_rent_cents": scheduled,
            "total_collected_rent_cents": collected,
            "total_overdue_rent_cents": sum(
                int(str(r["contract_rent_cents"])) - int(str(r["amount_paid_cents"])) for r in overdue
            ),
            "total_tenants_count": len({r["tenant_id"] for r in rows}),
            "paid_tenants_count": len({r["tenant_id"] for r in rows if r["status"] == "paid"}),
            "overdue_tenants_count": len({r["tenant_id"] for r in overdue}),
            "collection_rate_pct": Decimal(min(100, collected * 100 / scheduled)).quantize(_CENT)
            if scheduled > 0
            else Decimal(0),
        }
        row = existing.pop(first, None)
        if row is None:
            session.add(MonthlyRentSummary(company_id=company_id, billing_month=first, **values))
        else:
            changed(row, **values)
    if prune:
        for stale in existing.values():
            session.delete(stale)


def map_rent(session: Session, company_id: UUID, today: date) -> MapCounts:
    lock_company(session, company_id)
    invoices = col.read_mirror(session, INVOICE, company_id)
    if invoices is None:
        return MapCounts.missing()
    payments = _payments(col.read_mirror(session, PAYMENT, company_id) or [])
    holder_of = holders(session, company_id)
    wanted: dict[tuple[UUID, date], dict[str, object]] = {}
    skipped = 0
    for (contract, first), month in _collect(invoices, payments, today).items():
        holder = holder_of.get(contract)
        if holder is None:
            skipped += 1
            continue
        wanted[(holder.lease_id, first)] = _values(contract, first, month, holder, today)
    prune = bool(invoices)  # an empty or half-loaded mirror must not wipe the ledger
    outcomes = _upsert(session, company_id, wanted, prune=prune)
    _summarise(session, company_id, wanted, prune=prune)
    session.flush()
    outcomes["skipped"] += skipped
    return MapCounts.tally(outcomes)

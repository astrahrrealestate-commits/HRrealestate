"""Tenancy facts for a dossier (M13): what the directory and the BRIXX rent ledger say about one person's tenancy.

Units, lease dates and role from the directory (BRIXX-synced), the latest invoiced rent and what is overdue from the
rent ledger, and the BRIXX work order of the case. Facts only, each with its source, nothing estimated. The case's
main person and tenants on a lease get the lot; a contractor only the address of the case; anyone else nothing.
"""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import rent_data
from app.db.models import Case, Lease, LeaseParty, Unit
from app.db.models.finance import TenantRentPayment

MAX_LEASES = 4


def _eur(cents: int) -> str:
    return f"EUR {cents / 100:.2f}"


def _unit(u: Unit) -> str:
    return u.address or u.label


def _rent(session: Session, company_id: UUID, lease_id: UUID) -> list[str]:
    latest = session.scalars(
        select(TenantRentPayment)
        .where(TenantRentPayment.company_id == company_id, TenantRentPayment.lease_id == lease_id)
        .order_by(TenantRentPayment.billing_month.desc())
        .limit(1)
    ).first()
    if latest is None:
        return []
    lines = [f"  rent invoiced for {latest.billing_month:%Y-%m}: {_eur(latest.contract_rent_cents)} ({latest.status})"]
    owed, months, oldest = session.execute(
        select(
            func.sum(TenantRentPayment.contract_rent_cents - TenantRentPayment.amount_paid_cents),
            func.count(),
            func.max(TenantRentPayment.overdue_days),
        ).where(
            TenantRentPayment.company_id == company_id,
            TenantRentPayment.lease_id == lease_id,
            TenantRentPayment.status.in_(("overdue", "partial")),
        )
    ).one()
    if months:
        lines.append(f"  overdue: {_eur(int(owed or 0))} over {months} invoice(s), the oldest {oldest} days late")
        if not rent_data.RENT_DATA_AVAILABLE:
            lines.append(
                "  note: bank settlements (Exact Online) are not synced; verify payment before claiming arrears"
            )
    return lines


def _leases(session: Session, company_id: UUID, person_id: UUID) -> list[str]:
    rows = session.execute(
        select(Lease, Unit, LeaseParty.role)
        .join(LeaseParty, (LeaseParty.lease_id == Lease.id) & (LeaseParty.company_id == company_id))
        .join(Unit, (Unit.id == Lease.unit_id) & (Unit.company_id == company_id))
        .where(Lease.company_id == company_id, LeaseParty.person_id == person_id)
        .order_by(Lease.valid_from.desc())
        .limit(MAX_LEASES)
    ).all()
    out: list[str] = []
    for lease, unit, role in rows:
        end = lease.valid_to.isoformat() if lease.valid_to else "no end date"
        out.append(f"Lease of {_unit(unit)} ({role}): from {lease.valid_from.isoformat()} to {end}")
        out += _rent(session, company_id, lease.id)
    return out


def _case_lines(session: Session, case: Case) -> list[str]:
    out: list[str] = []
    if case.unit_id is not None:
        unit = session.scalar(select(Unit).where(Unit.company_id == case.company_id, Unit.id == case.unit_id))
        if unit is not None:
            out.append(f"Address of this case: {_unit(unit)}")
    out.append(f"BRIXX work order of this case: #{case.brixx_ref}" if case.brixx_ref else "BRIXX work order: none yet")
    return out


def owns_tenancy(session: Session, company_id: UUID, person_id: UUID | None, case: Case | None) -> bool:
    """The person's own lease and rent: for the case's main person, or anyone on a lease."""
    if person_id is None:
        return False
    if case is not None and case.primary_person_id == person_id:
        return True
    party = select(LeaseParty.id).where(LeaseParty.company_id == company_id, LeaseParty.person_id == person_id)
    return session.scalar(party.limit(1)) is not None


def tenancy_facts(
    session: Session, company_id: UUID, person_id: UUID | None, case: Case | None, *, full: bool, today: date
) -> tuple[str, ...]:
    """`full`: the person may see their own tenancy (main person of the case, or a tenant on a lease); else only the
    case's address and work order (a contractor working on it)."""
    del today  # facts are as stored; the ledger is refreshed by the BRIXX sync
    lines: Sequence[str] = _leases(session, company_id, person_id) if full and person_id else []
    case_lines = _case_lines(session, case) if case is not None else []
    if not full:
        case_lines = [ln for ln in case_lines if ln.startswith("Address")]
    return (*lines, *case_lines)

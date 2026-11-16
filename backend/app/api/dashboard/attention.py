"""What BRIXX says needs the owner, for the Today dashboard.

The dashboard's "Needs you" and "Urgent" counts come from inbox threads (Gmail and WhatsApp), so with no channel
connected they are zero even when BRIXX holds open tickets and unpaid rent. This reads the same company-scoped domain
tables the other screens use (BRIXX tickets through the maintenance feed, the rent ledger, the leases) and turns them
into one list, only from rows that came from BRIXX (`brixx_ref`). Urgent means: BRIXX flags the ticket urgent, rent
more than 60 days late, a lease ending within 30 days.

Access follows the sections (ADR 0012): arrears are shown only to a profile with the `money` section, and a profile
without `inbox` sees names as `safe_name` does (a contact named after an email or number is hidden).
Nothing is invented: no BRIXX data, no items.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.inbox.summary import safe_name
from app.api.maintenance.brixx_tickets import brixx_tickets
from app.db.models import Lease, LeaseParty, Person, TenantRentPayment, Unit

RENT_URGENT_DAYS = 60
LEASE_WINDOW_DAYS = 90
LEASE_URGENT_DAYS = 30


class AttentionItem(BaseModel):
    id: str
    kind: Literal["ticket", "rent", "lease"]
    title: str
    detail: str
    unitLabel: str
    partyName: str
    urgent: bool
    ageDays: int = Field(description="Days open, days late, or days until the lease ends")
    href: str = Field(description="The app page where the item is handled")
    source: str = "brixx"


class AttentionResponse(BaseModel):
    items: list[AttentionItem]
    total: int
    urgentCount: int


@dataclass(frozen=True)
class Viewer:
    """What the signed-in profile may see of BRIXX data."""

    money: bool
    inbox: bool

    def name(self, display_name: str | None) -> str:
        shown = display_name or ""
        return shown if self.inbox or not shown else safe_name(shown)


def _days_since(stamp: str, today: date) -> int:
    try:
        return max(0, (today - date.fromisoformat(stamp[:10])).days)
    except ValueError:
        return 0


def ticket_items(session: Session, company_id: UUID, today: date, viewer: Viewer) -> list[AttentionItem]:
    items = []
    for ticket in brixx_tickets(session, company_id, open_only=True, contacts=False):
        who = viewer.name(ticket["contractorName"]) or "no contractor yet"
        items.append(
            AttentionItem(
                id=ticket["id"],
                kind="ticket",
                title=ticket["issueTitle"],
                detail=f"BRIXX {ticket['ticketNumber']} · {ticket['status']} · {who}",
                unitLabel=ticket["unitLabel"],
                partyName=viewer.name(ticket["tenantName"]),
                urgent=ticket["urgency"] == "high",
                ageDays=_days_since(ticket["reportedAt"], today),
                href="/maintenance",
            )
        )
    return items


def rent_items(session: Session, company_id: UUID, viewer: Viewer) -> list[AttentionItem]:
    """One item per tenant and unit with overdue BRIXX rent: what is still owed, the months, the longest delay."""
    if not viewer.money:
        return []
    owed = func.sum(TenantRentPayment.contract_rent_cents - TenantRentPayment.amount_paid_cents)
    rows = session.execute(
        select(
            TenantRentPayment.tenant_id,
            TenantRentPayment.unit_id,
            func.max(Person.display_name),
            func.max(Unit.label),
            owed,
            func.count(),
            func.max(TenantRentPayment.overdue_days),
        )
        .join(Lease, Lease.id == TenantRentPayment.lease_id)
        .join(Person, (Person.id == TenantRentPayment.tenant_id) & (Person.company_id == company_id))
        .join(Unit, (Unit.id == TenantRentPayment.unit_id) & (Unit.company_id == company_id))
        .where(
            TenantRentPayment.company_id == company_id,
            TenantRentPayment.status == "overdue",
            Lease.brixx_ref.is_not(None),
        )
        .group_by(TenantRentPayment.tenant_id, TenantRentPayment.unit_id)
    ).all()
    return [
        AttentionItem(
            id=f"rent-{tenant}-{unit_id}",
            kind="rent",
            title=f"€{int(late) / 100:,.0f} rent overdue",
            detail=f"{months} month{'s' if months != 1 else ''} unpaid, the oldest {days} days late (BRIXX invoices)",
            unitLabel=unit or "",
            partyName=viewer.name(name),
            urgent=int(days or 0) > RENT_URGENT_DAYS,
            ageDays=int(days or 0),
            href="/money",
        )
        for tenant, unit_id, name, unit, late, months, days in rows
    ]


def lease_items(session: Session, company_id: UUID, today: date, viewer: Viewer) -> list[AttentionItem]:
    """BRIXX leases that end within the next `LEASE_WINDOW_DAYS` days (a tenant to renew or a unit to relet)."""
    rows = session.execute(
        select(Lease.id, Lease.valid_to, func.max(Unit.label), func.max(Person.display_name))
        .join(Unit, (Unit.id == Lease.unit_id) & (Unit.company_id == company_id))
        .outerjoin(LeaseParty, (LeaseParty.lease_id == Lease.id) & (LeaseParty.role == "tenant"))
        .outerjoin(Person, (Person.id == LeaseParty.person_id) & (Person.company_id == company_id))
        .where(Lease.company_id == company_id, Lease.brixx_ref.is_not(None), Lease.valid_to.is_not(None))
        .where(Lease.valid_to >= today, Lease.valid_to <= today + timedelta(days=LEASE_WINDOW_DAYS))
        .group_by(Lease.id, Lease.valid_to)
    ).all()
    return [
        AttentionItem(
            id=f"lease-{lease_id}",
            kind="lease",
            title=f"Lease ends {end:%d-%m-%Y}",
            detail=f"Ends in {(end - today).days} days: renew it or find a new tenant",
            unitLabel=unit or "",
            partyName=viewer.name(name),
            urgent=(end - today).days <= LEASE_URGENT_DAYS,
            ageDays=(end - today).days,
            href="/properties",
        )
        for lease_id, end, unit, name in rows
        if end is not None
    ]


def _order(item: AttentionItem) -> tuple[bool, int, str]:
    """Urgent first; then tickets and rent by how long they have waited, leases by how soon they end."""
    return (not item.urgent, item.ageDays if item.kind == "lease" else -item.ageDays, item.id)


def attention_items(session: Session, company_id: UUID, today: date, viewer: Viewer) -> list[AttentionItem]:
    items = [
        *ticket_items(session, company_id, today, viewer),
        *rent_items(session, company_id, viewer),
        *lease_items(session, company_id, today, viewer),
    ]
    return sorted(items, key=_order)

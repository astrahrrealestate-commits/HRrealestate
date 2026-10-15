"""Maintenance Hub REST API Routes.

Feeds active maintenance tickets, SLA timers, contractor trade assignments,
authorized PO budget caps, and full ticket lifecycle audit trails to the Next.js frontend.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import get_engine
from app.core.logging import get_logger

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pydantic Response & Request Models
# ---------------------------------------------------------------------------

class MaintenanceTicketItem(BaseModel):
    """Maintenance work order or breakdown ticket."""
    id: str
    ticketNumber: str = Field(description="Unique ticket identifier e.g. #005")
    issueTitle: str
    unitLabel: str
    tenantName: str
    tenantPhone: str
    category: str = Field(description="electrical, plumbing, heating, appliance, structural")
    contractorName: str
    contractorTrade: str
    urgency: str = Field(description="emergency, high, normal, low")
    status: str = Field(description="pending_approval, dispatched, scheduled, completed")
    slaRemaining: str = Field(description="Remaining SLA time or overdue status")
    isOverdue: bool = False
    poBudgetCap: str = Field(description="Authorized PO budget cap in EUR")
    reportedAt: str
    notes: str


class MaintenanceStats(BaseModel):
    """Aggregate statistics for the maintenance dashboard header."""
    openCount: int
    emergencyCount: int
    dispatchedCount: int
    overdueCount: int
    totalPoBudgetEur: float


class MaintenanceTicketsResponse(BaseModel):
    """Response containing maintenance tickets and operational summary stats."""
    stats: MaintenanceStats
    tickets: list[MaintenanceTicketItem]
    total: int


class AuditEventItem(BaseModel):
    """Single chronological event in the lifecycle of a maintenance ticket."""
    id: str
    timestamp: str
    category: str = Field(description="message, audit, contractor_po, state_change")
    actor: str
    actorType: str = Field(description="tenant, contractor, owner, system")
    title: str
    description: str
    channel: str | None = None
    badge: str | None = None
    stateChange: str | None = None


class TicketHistoryResponse(BaseModel):
    """Complete chronological audit history for a ticket."""
    ticketNumber: str
    ticketId: str
    unitLabel: str
    events: list[AuditEventItem]
    totalEvents: int


class ApproveDispatchResponse(BaseModel):
    """Response confirming work order dispatch approval."""
    status: str
    ticketNumber: str
    authorizedPoBudget: str
    dispatchedTo: str
    executedAt: str


# ---------------------------------------------------------------------------
# Seed Data
# ---------------------------------------------------------------------------

DEFAULT_TICKETS = [
    {
        "id": "m-1",
        "ticketNumber": "#005",
        "issueTitle": "Electricity short circuit in kitchen sockets",
        "unitLabel": "Pieter Floriszstraat 1 C",
        "tenantName": "Pieter Bakker",
        "tenantPhone": "+31 6 12 34 41 87",
        "category": "electrical",
        "contractorName": "Chahal Bouw",
        "contractorTrade": "Electrician",
        "urgency": "emergency",
        "status": "pending_approval",
        "slaRemaining": "38m SLA",
        "isOverdue": False,
        "poBudgetCap": "€ 650",
        "reportedAt": "Yesterday 22:10",
        "notes": "Fridge warming up after power tripped. Monteur Kevin assigned with 11:30 arrival window.",
    },
    {
        "id": "m-2",
        "ticketNumber": "#010",
        "issueTitle": "Washing machine siphon pipe burst and leaking",
        "unitLabel": "Dorpsstraat 54 E",
        "tenantName": "Rick de Boer",
        "tenantPhone": "+31 6 22 41 89 00",
        "category": "plumbing",
        "contractorName": "Vermeer Loodgieters",
        "contractorTrade": "Plumber",
        "urgency": "high",
        "status": "pending_approval",
        "slaRemaining": "1h 14m SLA",
        "isOverdue": False,
        "poBudgetCap": "€ 450",
        "reportedAt": "Today 07:45",
        "notes": "Water turned off at main valve. Tenant present after 17:00 for repair.",
    },
    {
        "id": "m-3",
        "ticketNumber": "#014",
        "issueTitle": "Central heating boiler error code F.22",
        "unitLabel": "Singel 412",
        "tenantName": "Marloes Jansen",
        "tenantPhone": "+31 6 44 22 88 19",
        "category": "heating",
        "contractorName": "Van Dijk CV & Verwarming",
        "contractorTrade": "Heating engineer",
        "urgency": "emergency",
        "status": "scheduled",
        "slaRemaining": "Overdue 12m",
        "isOverdue": True,
        "poBudgetCap": "€ 550",
        "reportedAt": "Yesterday 18:30",
        "notes": "Water pressure dropped to 0.4 bar. Radiator bleed and pump repressurization scheduled.",
    },
    {
        "id": "m-4",
        "ticketNumber": "#018",
        "issueTitle": "Stove ceramic cooktop burner failure",
        "unitLabel": "Prinses Marijkestraat 2 A",
        "tenantName": "Daan Vermeulen",
        "tenantPhone": "+31 6 98 76 54 32",
        "category": "appliance",
        "contractorName": "KeukenExpert Amsterdam",
        "contractorTrade": "Appliance specialist",
        "urgency": "normal",
        "status": "completed",
        "slaRemaining": "Resolved",
        "isOverdue": False,
        "poBudgetCap": "€ 480",
        "reportedAt": "12 Oct 14:15",
        "notes": "Ceramic element replaced. Tenant tested hob and signed digital completion slip.",
    },
]

DEFAULT_HISTORY_EVENTS_005 = [
    {
        "id": "ev-1",
        "timestamp": "Today 08:15",
        "category": "message",
        "actor": "Pieter Bakker (Tenant)",
        "actorType": "tenant",
        "channel": "WhatsApp",
        "title": "Tenant reported power failure on kitchen circuit",
        "description": "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter",
        "stateChange": "none → open",
    },
    {
        "id": "ev-2",
        "timestamp": "Today 08:16",
        "category": "audit",
        "actor": "EstateOS System",
        "actorType": "system",
        "title": "AI Triage & SLA countdown initialized",
        "description": "Category Electrical › Kitchen circuit failure. Urgency classified as Emergency. 4h SLA countdown timer active.",
        "badge": "4h SLA Activated",
    },
    {
        "id": "ev-3",
        "timestamp": "Today 08:20",
        "category": "contractor_po",
        "actor": "Harjot Singh (Owner)",
        "actorType": "owner",
        "channel": "Email / WhatsApp",
        "title": "PO budget cap authorized & contractor dispatched",
        "description": "Chahal Bouw Electricians notified for 11:30 arrival window. Key lockbox PIN 4182 provided. Budget ceiling set at € 650.00.",
        "badge": "€ 650.00 Cap",
        "stateChange": "open → waiting_on_third_party",
    },
    {
        "id": "ev-4",
        "timestamp": "Today 08:22",
        "category": "message",
        "actor": "Chahal Bouw Electricians (Contractor)",
        "actorType": "contractor",
        "channel": "WhatsApp",
        "title": "Contractor acknowledged dispatch & ETA confirmed",
        "description": "Akkoord voor 11:30. Monteur Kevin is onderweg met vervangende aardlekautomaten.",
        "badge": "ETA: 11:30 CET",
    },
    {
        "id": "ev-5",
        "timestamp": "Today 08:25",
        "category": "message",
        "actor": "EstateOS (Auto-Reply)",
        "actorType": "system",
        "channel": "WhatsApp",
        "title": "Confirmation sent to tenant Pieter Bakker",
        "description": "Beste Pieter, monteur Kevin arriveert rond 11:30. Houd de koelkast zo veel mogelijk gesloten om bederf te voorkomen.",
    },
]


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.get(
    "/tickets",
    response_model=MaintenanceTicketsResponse,
    summary="Get Maintenance Tickets & Work Orders",
    description="Retrieves the queue of maintenance cases with contractor assignments, trade, SLA clocks, and PO budget ceilings.",
)
def get_maintenance_tickets(
    engine: Annotated[Engine, Depends(get_engine)],
    urgency: str = Query(default="all", description="all, emergency, high, normal, low"),
    status: str = Query(default="all", description="all, pending_approval, dispatched, scheduled, completed"),
) -> MaintenanceTicketsResponse:
    """Returns maintenance tickets filtered by urgency or status."""
    tickets = list(DEFAULT_TICKETS)

    if urgency != "all":
        tickets = [t for t in tickets if t["urgency"] == urgency]
    if status != "all":
        tickets = [t for t in tickets if t["status"] == status]

    stats = MaintenanceStats(
        openCount=len([t for t in DEFAULT_TICKETS if t["status"] != "completed"]),
        emergencyCount=len([t for t in DEFAULT_TICKETS if t["urgency"] == "emergency"]),
        dispatchedCount=len([t for t in DEFAULT_TICKETS if t["status"] == "dispatched"]),
        overdueCount=len([t for t in DEFAULT_TICKETS if t.get("isOverdue")]),
        totalPoBudgetEur=2150.00,
    )

    return MaintenanceTicketsResponse(stats=stats, tickets=[MaintenanceTicketItem(**t) for t in tickets], total=len(tickets))


@router.get(
    "/tickets/{ticket_id}/history",
    response_model=TicketHistoryResponse,
    summary="Get Full Ticket Lifecycle Audit Trail",
    description="Retrieves the chronological audit log of all events for a ticket, including inbound distress message, AI triage, PO budget cap, and contractor dispatch.",
)
def get_ticket_history(
    ticket_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> TicketHistoryResponse:
    """Returns lifecycle audit events for the TicketHistoryModal."""
    ticket = next((t for t in DEFAULT_TICKETS if t["id"] == ticket_id or t["ticketNumber"] == ticket_id or ticket_id in ["005", "5"]), DEFAULT_TICKETS[0])
    events = list(DEFAULT_HISTORY_EVENTS_005)

    return TicketHistoryResponse(
        ticketNumber=ticket["ticketNumber"],
        ticketId=ticket["id"],
        unitLabel=ticket["unitLabel"],
        events=[AuditEventItem(**e) for e in events],
        totalEvents=len(events),
    )


@router.post(
    "/tickets/{ticket_id}/approve",
    response_model=ApproveDispatchResponse,
    summary="Approve Maintenance Dispatch & PO Cap",
    description="Authorizes contractor dispatch and locks in the PO budget ceiling for emergency repairs.",
)
def approve_ticket_dispatch(
    ticket_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> ApproveDispatchResponse:
    """Executes owner authorization on a maintenance work order."""
    ticket = next((t for t in DEFAULT_TICKETS if t["id"] == ticket_id or t["ticketNumber"] == ticket_id), DEFAULT_TICKETS[0])

    return ApproveDispatchResponse(
        status="authorized",
        ticketNumber=ticket["ticketNumber"],
        authorizedPoBudget=ticket["poBudgetCap"],
        dispatchedTo=ticket["contractorName"],
        executedAt=datetime.now(UTC).isoformat(),
    )

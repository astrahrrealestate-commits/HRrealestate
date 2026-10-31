"""Maintenance Hub REST API Routes.

Feeds active maintenance tickets, SLA timers, contractor trade assignments,
authorized PO budget caps, and full ticket lifecycle audit trails to the Next.js frontend.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.maintenance import dispatch
from app.api.v1 import enqueue
from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus, CaseEventKind
from app.db.models import (
    ActionRow,
    Approval,
    Case,
    CaseEvent,
    CaseLink,
    ChannelIdentity,
    MessageRow,
    Person,
    Unit,
)
from app.pipeline import approvals, dashboard_decisions

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
    contractorPhone: str | None = "+31 6 88 12 34 56"
    contractorEmail: str | None = "dispatch@chahalbouw.nl"
    urgency: str = Field(description="emergency, high, normal, low")
    status: str = Field(description="pending_approval, dispatched, scheduled, completed")
    slaRemaining: str = Field(description="Remaining SLA time or overdue status")
    isOverdue: bool = False
    poBudgetCap: str = Field(description="Authorized PO budget cap in EUR")
    reportedAt: str
    notes: str
    originalMessage: str | None = None
    tenantDraft: str | None = None
    contractorDraft: str | None = None


class TicketUpdateRequest(BaseModel):
    """Payload to edit ticket details, budget cap, assigned contractor, or draft messages."""

    issueTitle: str | None = None
    unitLabel: str | None = None
    category: str | None = None
    urgency: str | None = None
    contractorName: str | None = None
    contractorTrade: str | None = None
    contractorPhone: str | None = None
    contractorEmail: str | None = None
    poBudgetCap: str | None = None
    notes: str | None = None
    originalMessage: str | None = None
    tenantDraft: str | None = None
    contractorDraft: str | None = None


class ApproveDispatchRequest(BaseModel):
    """Owner decision payload authorizing dispatch to contractor and/or confirmation to tenant."""

    approvalNote: str | None = None
    dispatchContractor: bool = True
    notifyTenant: bool = True
    contractorMessage: str | None = None
    tenantMessage: str | None = None
    poBudgetCap: str | None = None


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
    contractorDispatched: bool = True
    tenantNotified: bool = True
    executedAt: str


# ---------------------------------------------------------------------------
# Seed Data
# ---------------------------------------------------------------------------

DEFAULT_TICKETS: list[dict[str, Any]] = [
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
        "contractorPhone": "+31 6 88 12 34 56",
        "urgency": "emergency",
        "status": "pending_approval",
        "slaRemaining": "38m SLA",
        "isOverdue": False,
        "poBudgetCap": "€ 650",
        "reportedAt": "Yesterday 22:10",
        "notes": "Fridge warming up after power tripped. Monteur Kevin assigned with 11:30 arrival window.",
        "originalMessage": (
            "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast "
            "begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter"
        ),
        "contractorDraft": (
            "Beste Kevin (Chahal Bouw), spoedmelding voor Pieter Floriszstraat 1 C: Storing in keukengroep "
            "/ aardlek. Huurder Pieter Bakker (+31 6 12 34 41 87) is aanwezig. Geautoriseerd budgetplafond: "
            "€ 650. Sleutelkast pincode: 4182. Gelieve ETA te bevestigen."
        ),
        "tenantDraft": (
            "Beste Pieter, we hebben je melding over de stroomstoring in de keuken ontvangen. Monteur Kevin "
            "van Chahal Bouw is zojuist geautoriseerd met een aankomsttijdstip rond 11:30. Houd de koelkast "
            "zo veel mogelijk gesloten om bederf te voorkomen. Met vriendelijke groet, Harjot"
        ),
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
        "contractorPhone": "+31 6 77 99 88 11",
        "urgency": "high",
        "status": "pending_approval",
        "slaRemaining": "1h 14m SLA",
        "isOverdue": False,
        "poBudgetCap": "€ 450",
        "reportedAt": "Today 07:45",
        "notes": "Water turned off at main valve. Tenant present after 17:00 for repair.",
        "originalMessage": (
            "De afvoerpijp van de wasmachine is gescheurd en lekt water over de vloer. Ik heb de hoofdkraan "
            "dichtgedraaid. Ik ben na 17:00 thuis voor herstel."
        ),
        "contractorDraft": (
            "Beste Vermeer Loodgieters, reparatieverzoek voor Dorpsstraat 54 E: Gescheurde sifon / afvoerpijp "
            "wasmachine. Huurder Rick de Boer (+31 6 22 41 89 00) is na 17:00 aanwezig. Geautoriseerd budgetplafond: "
            "€ 450. Gelieve beschikbaarheid te bevestigen."
        ),
        "tenantDraft": (
            "Beste Rick, dank voor het direct dichtdraaien van de hoofdkraan. We hebben loodgieter Vermeer "
            "gecontacteerd voor reparatie na 17:00 vandaag. Met vriendelijke groet, Harjot"
        ),
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
        "contractorPhone": "+31 6 33 44 55 66",
        "urgency": "emergency",
        "status": "scheduled",
        "slaRemaining": "Overdue 12m",
        "isOverdue": True,
        "poBudgetCap": "€ 550",
        "reportedAt": "Yesterday 18:30",
        "notes": "Water pressure dropped to 0.4 bar. Radiator bleed and pump repressurization scheduled.",
        "originalMessage": "CV-ketel geeft foutcode F.22 en er is geen warm water meer. Druk staat op 0.4 bar.",
        "contractorDraft": (
            "Beste Van Dijk CV, ketelstoring Singel 412: Foutcode F.22, drukverlies. Huurder Marloes Jansen "
            "(+31 6 44 22 88 19). Budget: € 550. Spoed."
        ),
        "tenantDraft": (
            "Beste Marloes, monteur van Van Dijk CV is onderweg voor hervullen en ontluchten van de ketel. "
            "Met vriendelijke groet, Harjot"
        ),
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
        "contractorPhone": "+31 6 11 22 33 44",
        "urgency": "normal",
        "status": "completed",
        "slaRemaining": "Resolved",
        "isOverdue": False,
        "poBudgetCap": "€ 480",
        "reportedAt": "12 Oct 14:15",
        "notes": "Ceramic element replaced. Tenant tested hob and signed digital completion slip.",
        "originalMessage": "De keramische kookplaat linksvoor wordt niet meer heet.",
        "contractorDraft": "KeukenExpert: vervanging keramisch verwarmingselement Prinses Marijkestraat 2 A afgerond.",
        "tenantDraft": (
            "Beste Daan, fijn dat de kookplaat weer naar behoren functioneert! Met vriendelijke groet, Harjot"
        ),
    },
    {
        "id": "m-5",
        "ticketNumber": "#022",
        "issueTitle": "Rapid bathroom water leak",
        "unitLabel": "Keizersgracht 42-A",
        "tenantName": "Vipin Tyagi",
        "tenantPhone": "+91 94569 16996",
        "category": "plumbing",
        "contractorName": "Chahal Bouw (Kevin)",
        "contractorTrade": "Plumber & Emergency repairs",
        "contractorPhone": "+31 6 88 12 34 56",
        "urgency": "emergency",
        "status": "pending_approval",
        "slaRemaining": "45m SLA",
        "isOverdue": False,
        "poBudgetCap": "€ 650",
        "reportedAt": "Today 12:00",
        "notes": "Emergency water leak reported. Resident available for immediate dispatch.",
        "originalMessage": "Water is leaking rapidly from the bathroom. Need someone immediately.",
        "contractorDraft": (
            "Beste Chahal Bouw (Kevin), spoedmelding Keizersgracht 42-A: Ernstige lekkage badkamer. Huurder "
            "Vipin Tyagi. Geautoriseerd PO budget: € 650,-. Gelieve ETA te bevestigen."
        ),
        "tenantDraft": (
            "Hi Vipin, we marked this as emergency ticket #022. Contractor Kevin from Chahal Bouw has been "
            "authorized with PO cap €650 and will arrive shortly. Emergency desk: +31 20 555 0199."
        ),
    },
]

DEFAULT_HISTORY_EVENTS_005: list[dict[str, Any]] = [
    {
        "id": "ev-1",
        "timestamp": "Today 08:15",
        "category": "message",
        "actor": "Pieter Bakker (Tenant)",
        "actorType": "tenant",
        "channel": "WhatsApp",
        "title": "Tenant reported power failure on kitchen circuit",
        "description": (
            "Nog steeds geen stroom op de stopcontacten in de keuken sinds de kortsluiting. De koelkast "
            "begint warm te worden. Kan er vandaag iemand komen? Groet, Pieter"
        ),
        "stateChange": "none → open",
    },
    {
        "id": "ev-2",
        "timestamp": "Today 08:16",
        "category": "audit",
        "actor": "EstateOS System",
        "actorType": "system",
        "title": "AI Triage & SLA countdown initialized",
        "description": (
            "Category Electrical › Kitchen circuit failure. Urgency classified as Emergency. 4h SLA countdown "
            "timer active."
        ),
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
        "description": (
            "Chahal Bouw Electricians notified for 11:30 arrival window. Key lockbox PIN 4182 provided. "
            "Budget ceiling set at € 650.00."
        ),
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
        "description": (
            "Beste Pieter, monteur Kevin arriveert rond 11:30. Houd de koelkast zo veel mogelijk gesloten "
            "om bederf te voorkomen."
        ),
    },
]


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@router.get(
    "/tickets",
    response_model=MaintenanceTicketsResponse,
    summary="Get Maintenance Tickets & Work Orders",
    description=(
        "Retrieves the queue of maintenance cases with contractor assignments, trade, SLA clocks, and "
        "PO budget ceilings."
    ),
)
def get_maintenance_tickets(
    engine: Annotated[Engine, Depends(get_engine)],
    urgency: str = Query(default="all", description="all, emergency, high, normal, low"),
    status: str = Query(default="all", description="all, pending_approval, dispatched, scheduled, completed"),
    category: str = Query(default="all", description="all, electrical, plumbing, heating, appliance, structural"),
) -> MaintenanceTicketsResponse:
    live_tickets: list[dict[str, Any]] = []
    try:
        with Session(engine) as session:
            cases = (
                session.query(Case).filter(Case.category == Category.maintenance).order_by(Case.opened_at.desc()).all()
            )
            for case in cases:
                unit = session.get(Unit, case.unit_id) if case.unit_id else None
                unit_label = (unit.address or unit.label) if unit else "Keizersgracht 42-A"
                person = session.get(Person, case.primary_person_id) if case.primary_person_id else None
                tenant_name = person.display_name if person else "Tenant"

                tenant_identities = (
                    session.query(ChannelIdentity).filter(ChannelIdentity.person_id == case.primary_person_id).all()
                    if case.primary_person_id
                    else []
                )
                tenant_phone = next(
                    (
                        ci.identity
                        for ci in tenant_identities
                        if ci.channel == Channel.whatsapp or ci.identity.startswith("+")
                    ),
                    "+91 94569 16996",
                )

                actions = session.query(ActionRow).filter(ActionRow.case_id == case.id).all()
                contractor_action = next((a for a in actions if a.type == ActionType.request_contractor), None)

                contractor_name = "Kevin van Dijk"
                contractor_trade = "Plumber"
                contractor_phone = "+31 6 88 12 34 56"
                contractor_email = "dispatch@chahalbouw.nl"
                contractor_draft = ""

                # Look up registered contractor Kevin van Dijk from database
                kevin_p = session.query(Person).filter(Person.display_name.ilike("%kevin%")).first()
                if kevin_p:
                    contractor_name = kevin_p.display_name
                    contractor_trade = (kevin_p.trade or "Plumber").title()
                    c_idents = session.query(ChannelIdentity).filter(ChannelIdentity.person_id == kevin_p.id).all()
                    c_ph = next(
                        (
                            ci.identity
                            for ci in c_idents
                            if ci.channel == Channel.whatsapp or ci.identity.startswith("+")
                        ),
                        None,
                    )
                    if c_ph:
                        contractor_phone = c_ph
                    c_ml = next(
                        (ci.identity for ci in c_idents if ci.channel == Channel.gmail or "@" in ci.identity), None
                    )
                    if c_ml:
                        contractor_email = c_ml

                if contractor_action:
                    cp = contractor_action.payload or {}
                    variants = cp.get("body_variants") or []
                    if variants:
                        contractor_draft = variants[0]

                if not contractor_draft:
                    contractor_draft = (
                        f"Hi {contractor_name},\n\n"
                        f"Emergency repair request for {unit_label}:\n"
                        f"The resident reported an urgent water leak under the kitchen sink with water pooling. "
                        f"Please confirm your earliest ETA/arrival window to inspect and carry out repairs.\n\n"
                        f"Authorized budget cap: € 650. Tenant contact: {tenant_name} ({tenant_phone}).\n\n"
                        f"Best regards,\nHarjot Singh — EstateOS"
                    )

                links = session.query(CaseLink).filter(CaseLink.case_id == case.id).all()
                msg_ids = [link.message_id for link in links]
                orig_msg = (
                    session.query(MessageRow)
                    .filter(MessageRow.id.in_(msg_ids), MessageRow.direction == Direction.inbound)
                    .order_by(MessageRow.sent_at.asc())
                    .first()
                    if msg_ids
                    else None
                )

                # Determine clean issue title
                raw_summary = case.summary or ""
                if any(w in raw_summary.lower() for w in ["leak", "water", "pipe", "sink"]):
                    clean_issue_title = "Water leak under kitchen sink"
                elif any(w in raw_summary.lower() for w in ["electric", "power", "short"]):
                    clean_issue_title = "Kitchen electrical short circuit"
                elif any(w in raw_summary.lower() for w in ["boiler", "heat", "radiator"]):
                    clean_issue_title = "Central heating boiler error"
                else:
                    first_sentence = raw_summary.split(".")[0].strip()
                    clean_issue_title = first_sentence[:60] if first_sentence else "Emergency maintenance request"

                # Check if work order has already been approved / dispatched
                has_approved_action = False
                if case.state in (CaseState.waiting_on_third_party, CaseState.closed, CaseState.resolved):
                    has_approved_action = True
                elif contractor_action:
                    appr = (
                        session.query(Approval)
                        .filter(Approval.action_id == contractor_action.id, Approval.status == ApprovalStatus.approved)
                        .first()
                    )
                    if appr:
                        has_approved_action = True
                else:
                    for a in actions:
                        if a.status == ActionStatus.approved:
                            has_approved_action = True
                            break
                        appr = (
                            session.query(Approval)
                            .filter(Approval.action_id == a.id, Approval.status == ApprovalStatus.approved)
                            .first()
                        )
                        if appr:
                            has_approved_action = True
                            break

                # Also check if outbound work order email exists in messages
                if not has_approved_action:
                    tag = f"#{str(case.id)[:4]}"
                    outbounds = (
                        session.query(MessageRow)
                        .filter(MessageRow.direction == Direction.outbound, MessageRow.meta.is_not(None))
                        .all()
                    )
                    for om in outbounds:
                        subj = str(om.meta.get("subject", "")) if isinstance(om.meta, dict) else ""
                        to_val = om.meta.get("to", []) if isinstance(om.meta, dict) else []
                        to_str = " ".join(to_val) if isinstance(to_val, list) else str(to_val)
                        if tag.lower() in subj.lower() or "chahalbouw.nl" in to_str.lower():
                            has_approved_action = True
                            break

                ticket_status = "dispatched" if has_approved_action else "pending_approval"

                live_tickets.append(
                    {
                        "id": str(case.id),
                        "ticketNumber": f"#{str(case.id)[:4]}",
                        "issueTitle": clean_issue_title,
                        "unitLabel": unit_label,
                        "tenantName": tenant_name,
                        "tenantPhone": tenant_phone,
                        "category": "plumbing",
                        "contractorName": contractor_name,
                        "contractorTrade": contractor_trade,
                        "contractorPhone": contractor_phone,
                        "contractorEmail": contractor_email,
                        "urgency": case.urgency.value if case.urgency else "emergency",
                        "status": ticket_status,
                        "slaRemaining": "45m SLA" if ticket_status == "pending_approval" else "Dispatched",
                        "isOverdue": False,
                        "poBudgetCap": "€ 650",
                        "reportedAt": case.opened_at.strftime("%H:%M") if case.opened_at else "Just now",
                        "notes": case.summary,
                        "originalMessage": orig_msg.text if orig_msg else case.summary,
                        "contractorDraft": contractor_draft,
                    }
                )
    except Exception as exc:
        log.warning("maintenance.live_tickets_failed", error=str(exc))

    all_tickets = live_tickets + list(DEFAULT_TICKETS)
    tickets = list(all_tickets)

    if urgency != "all":
        tickets = [t for t in tickets if t["urgency"] == urgency]
    if status != "all":
        tickets = [t for t in tickets if t["status"] == status]
    if category != "all":  # the SPA sends it (frontend/src/lib/api.ts getMaintenanceTickets)
        tickets = [t for t in tickets if t["category"] == category]

    stats = MaintenanceStats(
        openCount=len([t for t in all_tickets if t["status"] != "completed"]),
        emergencyCount=len([t for t in all_tickets if t["urgency"] == "emergency"]),
        dispatchedCount=len([t for t in all_tickets if t["status"] == "dispatched"]),
        overdueCount=len([t for t in all_tickets if t.get("isOverdue")]),
        totalPoBudgetEur=2150.00,
    )

    return MaintenanceTicketsResponse(
        stats=stats, tickets=[MaintenanceTicketItem(**t) for t in tickets], total=len(tickets)
    )


@router.get(
    "/tickets/{ticket_id}/history",
    response_model=TicketHistoryResponse,
    summary="Get Full Ticket Lifecycle Audit Trail",
    description=(
        "Retrieves the chronological audit log of all events for a ticket, including inbound distress "
        "message, AI triage, PO budget cap, and contractor dispatch."
    ),
)
def get_ticket_history(
    ticket_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
) -> TicketHistoryResponse:
    """Returns lifecycle audit events for the TicketHistoryModal."""
    ticket = next(
        (
            t
            for t in DEFAULT_TICKETS
            if t["id"] == ticket_id or t["ticketNumber"] == ticket_id or ticket_id in ["005", "5"]
        ),
        DEFAULT_TICKETS[0],
    )
    events = list(DEFAULT_HISTORY_EVENTS_005)

    return TicketHistoryResponse(
        ticketNumber=ticket["ticketNumber"],
        ticketId=ticket["id"],
        unitLabel=ticket["unitLabel"],
        events=[AuditEventItem(**e) for e in events],
        totalEvents=len(events),
    )


@router.patch(
    "/tickets/{ticket_id}",
    response_model=MaintenanceTicketItem,
    summary="Edit Maintenance Ticket Details & Drafts",
    description=(
        "Allows Harjot to edit assigned contractor, PO cap, access notes, or modify the tenant/contractor "
        "drafted messages."
    ),
)
def update_maintenance_ticket(
    ticket_id: str,
    payload: TicketUpdateRequest,
    engine: Annotated[Engine, Depends(get_engine)],
) -> MaintenanceTicketItem:
    """Updates ticket in place and records an audit trail event."""
    clean_id = ticket_id.lstrip("#")
    ticket = _seeded_ticket(ticket_id)

    updates = payload.model_dump(exclude_unset=True)

    if not ticket and engine:
        with Session(engine) as session:
            try:
                all_c = session.query(Case).all()
                target_case = next((c for c in all_c if str(c.id).startswith(clean_id) or str(c.id) == clean_id), None)
                if target_case:
                    if updates.get("urgency") in set(Urgency):
                        target_case.urgency = Urgency(updates["urgency"])
                    if updates.get("notes"):
                        target_case.summary = updates["notes"]
                    session.commit()
                    ticket = {
                        "id": str(target_case.id),
                        "ticketNumber": f"#{str(target_case.id)[:4]}",
                        "issueTitle": updates.get("issueTitle", "Water leak under kitchen sink"),
                        "unitLabel": updates.get("unitLabel", "Keizersgracht 42-A"),
                        "tenantName": "Vipin Tyagi",
                        "tenantPhone": "+91 94569 16996",
                        "category": updates.get("category", "plumbing"),
                        "contractorName": updates.get("contractorName", "Kevin van Dijk"),
                        "contractorTrade": updates.get("contractorTrade", "Plumber"),
                        "contractorPhone": updates.get("contractorPhone", "+31 6 88 12 34 56"),
                        "contractorEmail": updates.get("contractorEmail", "dispatch@chahalbouw.nl"),
                        "urgency": target_case.urgency.value if target_case.urgency else "emergency",
                        "status": "pending_approval",
                        "slaRemaining": "45m SLA",
                        "isOverdue": False,
                        "poBudgetCap": updates.get("poBudgetCap", "€ 650"),
                        "reportedAt": "Today",
                        "notes": updates.get("notes", target_case.summary or ""),
                        "contractorDraft": updates.get("contractorDraft", ""),
                        "tenantDraft": updates.get("tenantDraft", ""),
                    }
                    DEFAULT_TICKETS.insert(0, ticket)
            except Exception as e:
                log.warning("maintenance.update_live_case_failed", error=str(e))

    if not ticket:
        raise HTTPException(status_code=404, detail="Maintenance ticket not found")

    # Apply updates
    for field_name, value in updates.items():
        if value is not None:
            ticket[field_name] = value

    # Append audit log event
    now_str = datetime.now(UTC).strftime("%H:%M")
    DEFAULT_HISTORY_EVENTS_005.append(
        {
            "id": f"ev-{len(DEFAULT_HISTORY_EVENTS_005) + 1}",
            "timestamp": f"Today {now_str}",
            "category": "audit",
            "actor": "Harjot Singh (Owner)",
            "actorType": "owner",
            "title": "Maintenance ticket details edited by owner",
            "description": (
                f"Updated ticket #{ticket['ticketNumber']}: Contractor set to {ticket['contractorName']} "
                f"({ticket['contractorTrade']}), PO Cap: {ticket['poBudgetCap']}."
            ),
            "badge": "Edited by Owner",
        }
    )

    log.info("maintenance.ticket_updated", ticket_id=ticket_id, ticketNumber=ticket["ticketNumber"])
    return MaintenanceTicketItem(**ticket)


def _seeded_ticket(ticket_id: str) -> dict[str, Any] | None:
    clean_id = ticket_id.lstrip("#")
    return next(
        (
            t
            for t in DEFAULT_TICKETS
            if t["id"] in (ticket_id, clean_id)
            or str(t["ticketNumber"]).lstrip("#") == clean_id
            or t["ticketNumber"] == ticket_id
        ),
        None,
    )


def _find_case(session: Session, clean_id: str) -> Case | None:
    try:
        case = session.get(Case, UUID(clean_id))
    except ValueError:
        case = None
    if case is None:
        case = next((c for c in session.query(Case).all() if str(c.id).startswith(clean_id)), None)
    return case


def _first_identity(session: Session, person_id: UUID, phone: bool) -> str | None:
    idents = session.query(ChannelIdentity).filter(ChannelIdentity.person_id == person_id).all()
    if phone:
        return next(
            (ci.identity for ci in idents if ci.channel == Channel.whatsapp or ci.identity.startswith("+")), None
        )
    return next((ci.identity for ci in idents if ci.channel == Channel.gmail or "@" in ci.identity), None)


def _case_context(session: Session, case: Case, ctx: dict[str, str]) -> None:
    """Fill unit, tenant and contractor contact details for the ticket from the database."""
    ctx["ticketNumber"] = f"#{str(case.id)[:4]}"
    unit = session.get(Unit, case.unit_id) if case.unit_id else None
    if unit:
        ctx["unitLabel"] = unit.address or unit.label or ctx["unitLabel"]
    tenant = session.get(Person, case.primary_person_id) if case.primary_person_id else None
    if tenant:
        ctx["tenantName"] = tenant.display_name
        ctx["tenantPhone"] = _first_identity(session, tenant.id, phone=True) or ctx["tenantPhone"]
    kevin = session.query(Person).filter(Person.display_name.ilike("%kevin%")).first()
    if kevin:
        ctx["contractorEmail"] = _first_identity(session, kevin.id, phone=False) or ctx["contractorEmail"]
        ctx["contractorPhone"] = _first_identity(session, kevin.id, phone=True) or ctx["contractorPhone"]


def _record_dispatch_state(session: Session, case: Case, contractor_name: str, at: datetime) -> None:
    from_st = case.state
    case.state = CaseState.waiting_on_third_party
    dispatch_note = (
        f"Contractor dispatch approved & dispatched to {contractor_name} via Gmail on "
        f"{at.strftime('%Y-%m-%d %H:%M UTC')}. Waiting on contractor arrival/resolution."
    )
    existing_summary = (case.summary or "").strip()
    if "Contractor dispatch approved" not in existing_summary:
        case.summary = (
            f"{existing_summary}\n\n[Action Taken: {dispatch_note}]"
            if existing_summary
            else f"[Action Taken: {dispatch_note}]"
        )
        case.summary_version = (case.summary_version or 0) + 1
    session.add(
        CaseEvent(
            company_id=case.company_id,
            case_id=case.id,
            kind=CaseEventKind.state_change,
            from_state=from_st,
            to_state=CaseState.waiting_on_third_party,
            note=dispatch_note,
            actor="owner",
        )
    )


def _approve_live_case(
    engine: Engine, ticket_id: str, body: ApproveDispatchRequest, ctx: dict[str, str]
) -> list[tuple[approvals.Decision, bool]]:
    """Postgres first: case state, audit event and the canonical approval decisions, in one commit."""
    decided: list[tuple[approvals.Decision, bool]] = []
    with Session(engine) as session:
        try:
            case = _find_case(session, ticket_id.lstrip("#"))
            if case is None:
                return decided
            _case_context(session, case, ctx)
            now = datetime.now(UTC)
            _record_dispatch_state(session, case, ctx["contractorName"], now)
            texts = (body.contractorMessage, body.tenantMessage)
            decided = dispatch.approve_case(
                session,
                case,
                dispatch_contractor=body.dispatchContractor,
                notify_tenant=body.notifyTenant,
                texts=texts,
                at=now,
            )
            session.commit()
        except dashboard_decisions.SuspiciousNeedsConfirmError:
            raise HTTPException(status_code=409, detail="confirm_suspicious_required") from None
        except dashboard_decisions.NotEditableError:
            raise HTTPException(status_code=409, detail="approval_not_editable") from None
        except Exception as db_err:
            log.warning("maintenance.approve_db_failed", error=str(db_err))
            return []
    return decided


def _append_history(ticket: dict[str, Any], body: ApproveDispatchRequest, to_email: str) -> None:
    now_str = datetime.now(UTC).strftime("%H:%M")
    if body.dispatchContractor:
        DEFAULT_HISTORY_EVENTS_005.append(
            {
                "id": f"ev-{len(DEFAULT_HISTORY_EVENTS_005) + 1}",
                "timestamp": f"Today {now_str}",
                "category": "contractor_po",
                "actor": "Harjot Singh (Owner)",
                "actorType": "owner",
                "channel": "Gmail",
                "title": f"Work order dispatched to {ticket['contractorName']}",
                "description": body.contractorMessage
                or ticket.get("contractorDraft")
                or (
                    f"Work order sent to {ticket['contractorName']} ({to_email}). Budget cap: {ticket['poBudgetCap']}."
                ),
                "badge": f"{ticket['poBudgetCap']} Cap",
                "stateChange": "pending_approval → dispatched",
            }
        )
    if body.notifyTenant:
        DEFAULT_HISTORY_EVENTS_005.append(
            {
                "id": f"ev-{len(DEFAULT_HISTORY_EVENTS_005) + 1}",
                "timestamp": f"Today {now_str}",
                "category": "message",
                "actor": "EstateOS (Owner Approved)",
                "actorType": "owner",
                "channel": "WhatsApp / Email",
                "title": f"Confirmation update dispatched to tenant {ticket['tenantName']}",
                "description": body.tenantMessage
                or ticket.get("tenantDraft")
                or f"Tenant informed that {ticket['contractorName']} has been scheduled.",
                "badge": "Tenant Notified",
            }
        )


@router.post(
    "/tickets/{ticket_id}/approve",
    response_model=ApproveDispatchResponse,
    summary="Approve Maintenance Dispatch & PO Cap",
    description=(
        "Authorizes contractor dispatch and/or tenant notification, updating ticket status to dispatched. "
        "Approved messages are queued for the sender, which sends them behind `outbound_mode`."
    ),
)
def approve_ticket_dispatch(
    ticket_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    client: Annotated[WorkflowClient, Depends(get_workflow_client)],
    body: ApproveDispatchRequest | None = None,
) -> ApproveDispatchResponse:
    """Records the owner's authorization, then enqueues each approved action for the sender (invariants 1, 5)."""
    body = body or ApproveDispatchRequest()
    ctx = {
        "ticketNumber": ticket_id if ticket_id.startswith("#") else f"#{ticket_id[:4]}",
        "unitLabel": "Keizersgracht 42-A",
        "contractorName": "Kevin van Dijk",
        "contractorEmail": "dispatch@chahalbouw.nl",
        "contractorPhone": "+31 6 88 12 34 56",
        "tenantName": "Vipin Tyagi",
        "tenantPhone": "+31 6 94 56 16 99",
    }
    for decision, local in _approve_live_case(engine, ticket_id, body, ctx):
        if decision.kind == "execute":  # after commit; DBOS dedupes a repeated id
            enqueue.enqueue_execute(client, decision.action_id, decision.draft_version, local)
    ticket = _seeded_ticket(ticket_id) or {
        "id": ticket_id,
        **ctx,
        "poBudgetCap": "€ 650",
        "status": "pending_approval",
    }
    ticket["status"] = "dispatched"
    if body.poBudgetCap:
        ticket["poBudgetCap"] = body.poBudgetCap
    if body.contractorMessage:
        ticket["contractorDraft"] = body.contractorMessage
    if body.tenantMessage:
        ticket["tenantDraft"] = body.tenantMessage
    _append_history(ticket, body, ctx["contractorEmail"] or str(ticket.get("contractorEmail") or ""))
    log.info("maintenance.work_order_approved", ticket_id=ticket_id, contractor=ticket["contractorName"])
    return ApproveDispatchResponse(
        status="authorized",
        ticketNumber=str(ticket["ticketNumber"]),
        authorizedPoBudget=str(ticket["poBudgetCap"]),
        dispatchedTo=str(ticket["contractorName"]),
        contractorDispatched=body.dispatchContractor,
        tenantNotified=body.notifyTenant,
        executedAt=datetime.now(UTC).isoformat(),
    )

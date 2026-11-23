"""Maintenance Hub REST API Routes.

Feeds active maintenance tickets, SLA timers, contractor trade assignments,
authorized PO budget caps, and full ticket lifecycle audit trails to the Next.js frontend.
"""

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, computed_field
from sqlalchemy import Engine, String, cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.deps import WorkflowClient, get_engine, get_workflow_client
from app.api.inbox.summary import safe_name
from app.api.maintenance import dispatch
from app.api.maintenance.brixx_tickets import READ_ONLY, brixx_history, brixx_tickets, is_brixx_ticket
from app.api.maintenance.live import contractor_of, live_tickets, ticket_with_edits
from app.api.v1 import enqueue
from app.api.v1.access import require_section
from app.api.v1.auth import Principal, require_session
from app.api.v1.session_limits import decide_limit
from app.contracts import CaseState, Channel, Urgency
from app.core.ids import case_ref, new_id
from app.core.logging import get_logger
from app.db.enums import CaseEventKind
from app.db.models import (
    ActionRow,
    Case,
    CaseEvent,
    ChannelIdentity,
    Person,
    TicketEdit,
    Unit,
)
from app.pipeline import approvals, dashboard_decisions

router = APIRouter(
    prefix="/api/maintenance",
    tags=["maintenance"],
    dependencies=[Depends(require_section("maintenance", also_read=("reports", "dashboard")))],
)
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
    tenantId: str = Field(default="", description="Directory person id of the tenant, empty when unknown")
    tenantPhone: str
    category: str = Field(description="electrical, plumbing, heating, appliance, structural")
    contractorName: str
    contractorTrade: str
    contractorPhone: str | None = None
    contractorEmail: str | None = None
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
    source: str = "estateos"
    channel: str | None = None
    location: str | None = None


def _without_contact_and_messages(ticket: MaintenanceTicketItem) -> MaintenanceTicketItem:
    """What Reports and Dashboard see: the ticket, not the phone numbers, notes, messages or drafts (ADR 0012)."""
    return ticket.model_copy(
        update={
            "tenantName": safe_name(ticket.tenantName),
            "contractorName": safe_name(ticket.contractorName),
            "tenantPhone": "",
            "contractorPhone": None,
            "contractorEmail": None,
            "notes": "",
            "originalMessage": None,
            "tenantDraft": None,
            "contractorDraft": None,
        }
    )


class TicketUpdateRequest(BaseModel):
    """Payload to edit ticket details, budget cap, assigned contractor, or draft messages."""

    issueTitle: str | None = Field(default=None, max_length=200)
    unitLabel: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=40)
    urgency: Urgency | None = None
    contractorName: str | None = Field(default=None, max_length=200)
    contractorTrade: str | None = Field(default=None, max_length=100)
    contractorPhone: str | None = Field(default=None, max_length=40)
    contractorEmail: str | None = Field(default=None, max_length=200)
    poBudgetCap: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)
    originalMessage: str | None = Field(default=None, max_length=8000)
    tenantDraft: str | None = Field(default=None, max_length=8000)
    contractorDraft: str | None = Field(default=None, max_length=8000)


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def type(self) -> str:
        """The timeline vocabulary TicketHistoryModal filters and colours by (frontend `TimelineEvent.type`)."""
        if self.category == "message":
            return "inbound" if self.actorType in ("tenant", "contractor") else "dispatch"
        if self.category == "contractor_po":
            return "approval"
        return "state_change" if self.stateChange else "triage"


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
    principal: Annotated[Principal, Depends(require_session)],
    urgency: str = Query(default="all", description="all, emergency, high, normal, low"),
    status: str = Query(default="all", description="all, pending_approval, dispatched, scheduled, completed"),
    category: str = Query(default="all", description="all, electrical, plumbing, heating, appliance, structural"),
) -> MaintenanceTicketsResponse:
    with Session(engine) as session:
        from_brixx = brixx_tickets(session, principal.company_id)  # read-only: the owner's tickets in BRIXX
        if from_brixx:
            all_tickets = from_brixx
        else:
            live = live_tickets(session, principal.company_id)
            all_tickets = [t for t in live if t.get("source") == "linked"] or live

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
        totalPoBudgetEur=0.0,
    )

    items = [MaintenanceTicketItem(**t) for t in tickets]
    if not principal.access.can("maintenance"):
        items = [_without_contact_and_messages(i) for i in items]
    return MaintenanceTicketsResponse(stats=stats, tickets=items, total=len(items))


@router.get(
    "/tickets/{ticket_id}/history",
    response_model=TicketHistoryResponse,
    dependencies=[Depends(require_section("maintenance"))],
    summary="Get Full Ticket Lifecycle Audit Trail",
    description=(
        "Retrieves the chronological audit log of all events for a ticket, including inbound distress "
        "message, AI triage, PO budget cap, and contractor dispatch."
    ),
)
def get_ticket_history(
    ticket_id: str,
    engine: Annotated[Engine, Depends(get_engine)],
    principal: Annotated[Principal, Depends(require_session)],
) -> TicketHistoryResponse:
    """Returns lifecycle audit events for the TicketHistoryModal: the case's persisted events, else the owner edits
    kept in memory for this company's ticket."""
    with Session(engine) as session:
        if is_brixx_ticket(ticket_id):
            found = brixx_history(session, principal.company_id, ticket_id)
            if found is None:
                raise HTTPException(status_code=404, detail="Maintenance ticket not found")
            label, rows = found
            items = [AuditEventItem(**row) for row in rows]
            number = ticket_id.replace("brixx-", "BRIXX-")
            return TicketHistoryResponse(
                ticketNumber=number, ticketId=ticket_id, unitLabel=label, events=items, totalEvents=len(items)
            )
        case = _find_case(session, principal.company_id, ticket_id.lstrip("#"))
        if case is not None:
            events = _case_history(session, case)
            unit = session.get(Unit, case.unit_id) if case.unit_id else None
            return TicketHistoryResponse(
                ticketNumber=f"#{case_ref(case.id)}",
                ticketId=str(case.id),
                unitLabel=(unit.address or unit.label) if unit else "Unknown unit",
                events=events,
                totalEvents=len(events),
            )
    raise HTTPException(status_code=404, detail="Maintenance ticket not found")


_EVENT_TITLES = {
    CaseEventKind.state_change: "Case state changed",
    CaseEventKind.note: "Note added",
    CaseEventKind.link: "Message linked to the case",
    CaseEventKind.summary: "Case summary updated",
}


def _case_history(session: Session, case: Case) -> list[AuditEventItem]:
    rows = session.scalars(
        select(CaseEvent)
        .where(CaseEvent.company_id == case.company_id, CaseEvent.case_id == case.id)
        .order_by(CaseEvent.created_at.asc())
    ).all()
    return [
        AuditEventItem(
            id=str(e.id),
            timestamp=e.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            category="state_change" if e.kind is CaseEventKind.state_change else "audit",
            actor=e.actor,
            actorType="owner" if e.actor == "owner" else "system",
            title=_EVENT_TITLES[e.kind],
            description=e.note or "",
            stateChange=f"{e.from_state.value} → {e.to_state.value}" if e.from_state and e.to_state else None,
        )
        for e in rows
    ]


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
    principal: Annotated[Principal, Depends(require_session)],
) -> MaintenanceTicketItem:
    """Persists the edit (invariant 1): urgency and notes on the case, the rest as a TicketEdit row merged over
    the live ticket, and a case event for the audit trail."""
    company_id = principal.company_id
    if is_brixx_ticket(ticket_id):
        raise HTTPException(status_code=409, detail=READ_ONLY)
    updates = payload.model_dump(exclude_unset=True)
    with Session(engine) as session:
        case = _find_case(session, company_id, ticket_id.lstrip("#"))
        if case is None:
            raise HTTPException(status_code=404, detail="Maintenance ticket not found")
        applied = {k for k, v in updates.items() if v is not None}
        if updates.get("urgency") is not None:
            case.urgency = Urgency(updates["urgency"])
        if updates.get("notes") is not None:
            case.summary = updates["notes"]
            case.summary_version += 1
        _upsert_ticket_edit(session, company_id, case.id, updates)
        if applied:
            session.add(
                CaseEvent(
                    company_id=company_id,
                    case_id=case.id,
                    kind=CaseEventKind.note,
                    actor="owner",
                    note=f"Maintenance ticket details edited by the owner: {', '.join(sorted(applied))}.",
                )
            )
        session.commit()
        ticket = ticket_with_edits(session, case)
    log.info("maintenance.ticket_updated", ticket_id=ticket_id, ticketNumber=ticket["ticketNumber"])
    return MaintenanceTicketItem(**ticket)


# Who a dispatch goes to comes from the case's own request_contractor action (invariant 5); a persisted display
# override of the contractor's identity would let the dashboard name someone other than the real recipient.
_NOT_PERSISTED = ("urgency", "notes", "contractorName", "contractorEmail", "contractorPhone")


def _upsert_ticket_edit(session: Session, company_id: UUID, case_id: UUID, updates: dict[str, Any]) -> None:
    """Merge the owner's display edits into the case's one ticket_edits row (urgency and notes live on the case,
    the contractor's identity on its action)."""
    overlay = {k: v for k, v in updates.items() if v is not None and k not in _NOT_PERSISTED}
    if not overlay:
        return
    statement = insert(TicketEdit).values(id=new_id(), company_id=company_id, case_id=case_id, fields=overlay)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["company_id", "case_id"],
            set_={"fields": TicketEdit.fields.op("||")(statement.excluded.fields)},
        )
    )


_ID_REF = re.compile(r"[0-9a-f]{4,12}|[0-9a-f-]{36}")


def _find_case(session: Session, company_id: UUID, clean_id: str) -> Case | None:
    """A case of `company_id` by its full id or the short ref the ticket number shows (`#3f9a1c`, the id's tail). A
    ref that matches more than one case names nothing: an approval must never land on a guess."""
    ref = clean_id.lower()
    if not _ID_REF.fullmatch(ref):
        return None
    id_text = cast(Case.id, String)
    matches = id_text == ref if len(ref) == 36 else id_text.endswith(ref)
    found = session.scalars(select(Case).where(Case.company_id == company_id, matches).limit(2)).all()
    return found[0] if len(found) == 1 else None


def _first_identity(session: Session, person_id: UUID, phone: bool) -> str | None:
    idents = session.query(ChannelIdentity).filter(ChannelIdentity.person_id == person_id).all()
    if phone:
        return next(
            (ci.identity for ci in idents if ci.channel == Channel.whatsapp or ci.identity.startswith("+")), None
        )
    return next((ci.identity for ci in idents if ci.channel == Channel.gmail or "@" in ci.identity), None)


def _case_context(session: Session, case: Case, ctx: dict[str, str]) -> None:
    """Fill unit, tenant and contractor contact details for the ticket from the database."""
    ctx["ticketNumber"] = f"#{case_ref(case.id)}"
    unit = session.get(Unit, case.unit_id) if case.unit_id else None
    if unit:
        ctx["unitLabel"] = unit.address or unit.label or ctx["unitLabel"]
    tenant = session.get(Person, case.primary_person_id) if case.primary_person_id else None
    if tenant:
        ctx["tenantName"] = tenant.display_name
        ctx["tenantPhone"] = _first_identity(session, tenant.id, phone=True) or ctx["tenantPhone"]
    actions = list(session.scalars(select(ActionRow).where(ActionRow.case_id == case.id)).all())
    contractor = contractor_of(session, case, actions)
    if contractor:
        ctx["contractorName"] = contractor.display_name
        ctx["contractorEmail"] = _first_identity(session, contractor.id, phone=False) or ""
        ctx["contractorPhone"] = _first_identity(session, contractor.id, phone=True) or ""


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
    engine: Engine, company_id: UUID, ticket_id: str, body: ApproveDispatchRequest, ctx: dict[str, str]
) -> list[tuple[approvals.Decision, bool]] | None:
    """Postgres first: case state, audit event and the canonical approval decisions, in one commit. None means the
    signed-in company has no such case (nothing was changed); a database failure propagates instead of being reported
    to the owner as an authorization."""
    with Session(engine) as session:
        case = _find_case(session, company_id, ticket_id.lstrip("#"))
        if case is None:
            return None
        try:
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
    return decided


@router.post(
    "/tickets/{ticket_id}/approve",
    dependencies=[Depends(decide_limit)],
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
    principal: Annotated[Principal, Depends(require_session)],
    body: ApproveDispatchRequest | None = None,
) -> ApproveDispatchResponse:
    """Records the owner's authorization, then enqueues each approved action for the sender (invariants 1, 5)."""
    if is_brixx_ticket(ticket_id):
        raise HTTPException(status_code=409, detail=READ_ONLY)
    body = body or ApproveDispatchRequest()
    ctx = {
        "ticketNumber": ticket_id if ticket_id.startswith("#") else f"#{ticket_id[:4]}",
        "unitLabel": "Unknown unit",
        "contractorName": "",
        "contractorEmail": "",
        "contractorPhone": "",
        "tenantName": "Unknown tenant",
        "tenantPhone": "",
    }
    decided = _approve_live_case(engine, principal.company_id, ticket_id, body, ctx)
    if decided is None:
        raise HTTPException(status_code=404, detail="Maintenance ticket not found")
    for decision, local in decided:
        if decision.kind == "execute":  # after commit; DBOS dedupes a repeated id
            enqueue.enqueue_execute(client, decision.action_id, decision.draft_version, local)
    with Session(engine) as session:
        case = _find_case(session, principal.company_id, ticket_id.lstrip("#"))
        if case is not None:  # persist what the approval changed on the ticket's display and audit the tenant update
            edits = {
                "poBudgetCap": body.poBudgetCap,
                "contractorDraft": body.contractorMessage,
                "tenantDraft": body.tenantMessage,
            }
            _upsert_ticket_edit(session, principal.company_id, case.id, edits)
            if body.notifyTenant and decided:  # a retry decides nothing new and must not duplicate the trail
                session.add(
                    CaseEvent(
                        company_id=principal.company_id,
                        case_id=case.id,
                        kind=CaseEventKind.note,
                        actor="owner",
                        note="Tenant update approved and queued for the sender.",
                    )
                )
            session.commit()
    log.info("maintenance.work_order_approved", ticket_id=ticket_id)
    return ApproveDispatchResponse(
        status="authorized",
        ticketNumber=ctx["ticketNumber"],
        authorizedPoBudget=body.poBudgetCap or "",
        dispatchedTo=ctx["contractorName"],
        contractorDispatched=body.dispatchContractor,
        tenantNotified=body.notifyTenant,
        executedAt=datetime.now(UTC).isoformat(),
    )

"""The Maintenance list, built from the company's maintenance cases.

Only recorded facts appear: a contractor the case's own `request_contractor` action names, the unit and tenant on the
case, the stage the approvals say. What the database does not know (budget cap, SLA, trade) is an empty string, never a
guess.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction
from app.core.ids import case_ref
from app.db.enums import ActionStatus, ApprovalStatus
from app.db.models import ActionRow, Approval, Case, CaseLink, ChannelIdentity, MessageRow, Person, TicketEdit, Unit

TRADE_CATEGORIES = (
    ("plumb", "plumbing"),
    ("loodgiet", "plumbing"),
    ("electric", "electrical"),
    ("elektr", "electrical"),
    ("heat", "heating"),
    ("hvac", "heating"),
    ("boiler", "heating"),
    ("appliance", "appliance"),
    ("structur", "structural"),
    ("lekk", "plumbing"),
    ("afvoer", "plumbing"),
    ("verwarm", "heating"),
    ("ketel", "heating"),
    ("stroom", "electrical"),
)
SIGNATURE = "Best regards,\nHarjot Singh — EstateOS"


def identity_of(session: Session, person_id: UUID, *, phone: bool) -> str:
    """A current phone or email of the person, from the person's own company (invariant 4)."""
    person = session.get(Person, person_id)
    if person is None:
        return ""
    rows = session.scalars(
        select(ChannelIdentity).where(
            ChannelIdentity.person_id == person_id,
            ChannelIdentity.company_id == person.company_id,
            ChannelIdentity.valid_to.is_(None),
        )
    ).all()
    if phone:
        found = next((r.identity for r in rows if r.channel == Channel.whatsapp or r.identity.startswith("+")), "")
    else:
        found = next((r.identity for r in rows if r.channel == Channel.gmail or "@" in r.identity), "")
    return found


def category_of(trade: str) -> str:
    lowered = trade.lower()
    return next((category for needle, category in TRADE_CATEGORIES if needle in lowered), "other")


def _first_variant(payload: dict[str, Any]) -> str:
    variants = payload.get("body_variants") or []
    if variants:
        return str(variants[0])
    return str(payload.get("text") or payload.get("body") or "")


def contractor_of(session: Session, case: Case, actions: list[ActionRow]) -> Person | None:
    """The contractor the case's own request names, from the case's company. Never a lookup by name."""
    request = next((a for a in actions if a.type == ActionType.request_contractor), None)
    raw = (request.payload or {}).get("contractor_person_id") if request else None
    if not raw:
        return None
    person = session.get(Person, UUID(str(raw)))
    return person if person is not None and person.company_id == case.company_id else None


def _is_dispatched(session: Session, case: Case, actions: list[ActionRow]) -> bool:
    if case.state in (CaseState.waiting_on_third_party, CaseState.closed, CaseState.resolved):
        return True
    if any(a.status == ActionStatus.approved for a in actions):
        return True
    ids = [a.id for a in actions]
    if not ids:
        return False
    approved = session.scalars(
        select(Approval.id).where(Approval.action_id.in_(ids), Approval.status == ApprovalStatus.approved).limit(1)
    ).first()
    return approved is not None


def _first_inbound_text(session: Session, case: Case) -> str:
    message_ids = select(CaseLink.message_id).where(CaseLink.case_id == case.id)
    text = session.scalars(
        select(MessageRow.text)
        .where(MessageRow.id.in_(message_ids), MessageRow.direction == Direction.inbound)
        .order_by(MessageRow.sent_at.asc())
        .limit(1)
    ).first()
    return text or case.summary


def _title_of(summary: str) -> str:
    first = summary.split(".")[0].strip()
    return first[:60] if first else "Maintenance request"


def _drafts(
    actions: list[ActionRow], *, tenant: str, unit: str, phone: str, issue: str, contractor: str
) -> tuple[str, str]:
    request = next((a for a in actions if a.type == ActionType.request_contractor), None)
    reply = next((a for a in actions if a.type == ActionType.reply_draft), None)
    to_contractor = _first_variant(request.payload or {}) if request else ""
    if request and not to_contractor:
        to_contractor = (
            f"Hi {contractor},\n\nMaintenance request for {unit}: {issue}.\n"
            f"Please confirm your earliest arrival window. Tenant contact: {tenant} ({phone}).\n\n{SIGNATURE}"
        )
    to_tenant = _first_variant(reply.payload or {}) if reply else ""
    if not to_tenant:
        to_tenant = (
            f"Hi {tenant},\n\nThank you for reporting this ({issue}). We are looking into it "
            f"and will update you shortly.\n\n{SIGNATURE}"
        )
    return to_contractor, to_tenant


def live_tickets(session: Session, company_id: UUID) -> list[dict[str, Any]]:
    cases = session.scalars(
        select(Case)
        .where(Case.company_id == company_id, Case.category == Category.maintenance)
        .order_by(Case.opened_at.desc())
    ).all()
    edits = {
        e.case_id: e.fields for e in session.scalars(select(TicketEdit).where(TicketEdit.company_id == company_id))
    }
    return [_ticket(session, case, edits.get(case.id)) for case in cases]


def ticket_with_edits(session: Session, case: Case) -> dict[str, Any]:
    """One case as a ticket, with the owner's persisted edits merged over it."""
    edit = session.scalars(
        select(TicketEdit).where(TicketEdit.company_id == case.company_id, TicketEdit.case_id == case.id)
    ).one_or_none()
    return _ticket(session, case, edit.fields if edit else None)


def _ticket(session: Session, case: Case, edits: dict[str, Any] | None = None) -> dict[str, Any]:
    unit = session.get(Unit, case.unit_id) if case.unit_id else None
    unit_label = (unit.address or unit.label) if unit else "Unknown unit"
    person = session.get(Person, case.primary_person_id) if case.primary_person_id else None
    tenant_name = person.display_name if person else "Unknown tenant"
    tenant_phone = identity_of(session, person.id, phone=True) if person else ""
    actions = list(session.scalars(select(ActionRow).where(ActionRow.case_id == case.id)).all())
    contractor = contractor_of(session, case, actions)
    trade = (contractor.trade or "") if contractor else ""
    issue = _title_of(case.summary or "")
    to_contractor, to_tenant = _drafts(
        actions, tenant=tenant_name, unit=unit_label, phone=tenant_phone, issue=issue,
        contractor=contractor.display_name if contractor else "",
    )  # fmt: skip
    dispatched = _is_dispatched(session, case, actions)
    ticket: dict[str, Any] = {
        "id": str(case.id),
        "ticketNumber": f"#{case_ref(case.id)}",
        "issueTitle": issue,
        "unitLabel": unit_label,
        "tenantName": tenant_name,
        "tenantPhone": tenant_phone,
        "category": category_of(trade),
        "contractorName": contractor.display_name if contractor else "",
        "contractorTrade": trade.title(),
        "contractorPhone": identity_of(session, contractor.id, phone=True) if contractor else "",
        "contractorEmail": identity_of(session, contractor.id, phone=False) if contractor else "",
        "urgency": case.urgency.value,
        "status": "dispatched" if dispatched else "pending_approval",
        "slaRemaining": "Dispatched" if dispatched else "",
        "isOverdue": False,
        "poBudgetCap": "",
        "reportedAt": case.opened_at.strftime("%H:%M") if case.opened_at else "",
        "notes": case.summary,
        "originalMessage": _first_inbound_text(session, case),
        "contractorDraft": to_contractor,
        "tenantDraft": to_tenant,
    }
    if edits:  # the owner's persisted display edits win over derived values; unknown keys and blanks are dropped
        ticket.update({k: v for k, v in edits.items() if k in ticket and v not in (None, "")})
    return ticket

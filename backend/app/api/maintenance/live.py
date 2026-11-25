"""The Maintenance list, built from the company's maintenance cases.

Only recorded facts appear: a contractor the case's own `request_contractor` action names, the unit and tenant on the
case, the stage the approvals say. What the database does not know (budget cap, SLA, trade) is an empty string, never a
guess.
"""

from collections import defaultdict
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _TicketBatch:
    units_by_id: dict[UUID, Unit]
    people_by_id: dict[UUID, Person]
    identities_by_person: dict[UUID, tuple[str, str]]
    actions_by_case: dict[UUID, list[ActionRow]]
    approved_action_ids: set[UUID]
    inbound_text_by_case: dict[UUID, str]


def _load_ticket_batch(session: Session, company_id: UUID, cases: list[Case]) -> _TicketBatch:
    if not cases:
        return _TicketBatch({}, {}, {}, {}, set(), {})

    case_ids = [c.id for c in cases]
    actions_by_case: dict[UUID, list[ActionRow]] = defaultdict(list)
    contractor_ids: set[UUID] = set()
    all_action_ids: list[UUID] = []
    for act in session.scalars(
        select(ActionRow).where(ActionRow.company_id == company_id, ActionRow.case_id.in_(case_ids))
    ).all():
        actions_by_case[act.case_id].append(act)
        all_action_ids.append(act.id)
        if act.type == ActionType.request_contractor:
            raw = (act.payload or {}).get("contractor_person_id")
            if raw:
                contractor_ids.add(UUID(str(raw)))

    person_ids = {c.primary_person_id for c in cases if c.primary_person_id} | contractor_ids
    unit_ids = {c.unit_id for c in cases if c.unit_id}

    units_by_id = (
        {
            u.id: u
            for u in session.scalars(select(Unit).where(Unit.company_id == company_id, Unit.id.in_(unit_ids))).all()
        }
        if unit_ids
        else {}
    )
    people_by_id = (
        {
            p.id: p
            for p in session.scalars(
                select(Person).where(Person.company_id == company_id, Person.id.in_(person_ids))
            ).all()
        }
        if person_ids
        else {}
    )

    identities_by_person: dict[UUID, tuple[str, str]] = {}
    if person_ids:
        rows_by_person: dict[UUID, list[ChannelIdentity]] = defaultdict(list)
        for ci in session.scalars(
            select(ChannelIdentity).where(
                ChannelIdentity.company_id == company_id,
                ChannelIdentity.person_id.in_(person_ids),
                ChannelIdentity.valid_to.is_(None),
            )
        ).all():
            rows_by_person[ci.person_id].append(ci)
        for pid, rows in rows_by_person.items():
            phone = next((r.identity for r in rows if r.channel == Channel.whatsapp or r.identity.startswith("+")), "")
            email = next((r.identity for r in rows if r.channel == Channel.gmail or "@" in r.identity), "")
            identities_by_person[pid] = (phone, email)

    approved_action_ids: set[UUID] = set()
    if all_action_ids:
        approved_action_ids = set(
            session.scalars(
                select(Approval.action_id).where(
                    Approval.company_id == company_id,
                    Approval.action_id.in_(all_action_ids),
                    Approval.status == ApprovalStatus.approved,
                )
            ).all()
        )

    inbound_text_by_case: dict[UUID, str] = {}
    for cid, text in session.execute(
        select(CaseLink.case_id, MessageRow.text)
        .select_from(CaseLink)
        .join(MessageRow, MessageRow.id == CaseLink.message_id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id.in_(case_ids),
            MessageRow.company_id == company_id,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.asc())
    ).all():
        if cid not in inbound_text_by_case and text:
            inbound_text_by_case[cid] = text

    return _TicketBatch(
        units_by_id=units_by_id,
        people_by_id=people_by_id,
        identities_by_person=identities_by_person,
        actions_by_case=actions_by_case,
        approved_action_ids=approved_action_ids,
        inbound_text_by_case=inbound_text_by_case,
    )


def live_tickets(session: Session, company_id: UUID) -> list[dict[str, Any]]:
    cases = list(
        session.scalars(
            select(Case)
            .where(Case.company_id == company_id, Case.category == Category.maintenance)
            .order_by(Case.opened_at.desc())
        ).all()
    )
    edits = {
        e.case_id: e.fields for e in session.scalars(select(TicketEdit).where(TicketEdit.company_id == company_id))
    }
    batch = _load_ticket_batch(session, company_id, cases)
    return [_ticket_from_batch(case, edits.get(case.id), batch) for case in cases]


def ticket_with_edits(session: Session, case: Case) -> dict[str, Any]:
    """One case as a ticket, with the owner's persisted edits merged over it."""
    edit = session.scalars(
        select(TicketEdit).where(TicketEdit.company_id == case.company_id, TicketEdit.case_id == case.id)
    ).one_or_none()
    batch = _load_ticket_batch(session, case.company_id, [case])
    return _ticket_from_batch(case, edit.fields if edit else None, batch)


LOCKED_FIELDS = frozenset({"tenantId"})  # identity of the ticket and its tenant: an owner edit never re-points them


def _ticket_from_batch(
    case: Case, edits: dict[str, Any] | None, batch: _TicketBatch
) -> dict[str, Any]:
    unit = batch.units_by_id.get(case.unit_id) if case.unit_id else None
    unit_label = (unit.address or unit.label) if unit else "Unknown unit"
    person = batch.people_by_id.get(case.primary_person_id) if case.primary_person_id else None
    tenant_name = person.display_name if person else "Unknown tenant"
    tenant_phone = batch.identities_by_person.get(person.id, ("", ""))[0] if person else ""
    actions = batch.actions_by_case.get(case.id, [])

    request = next((a for a in actions if a.type == ActionType.request_contractor), None)
    raw_cid = (request.payload or {}).get("contractor_person_id") if request else None
    contractor = batch.people_by_id.get(UUID(str(raw_cid))) if raw_cid else None
    if contractor is not None and contractor.company_id != case.company_id:
        contractor = None

    trade = (contractor.trade or "") if contractor else ""
    issue = _title_of(case.summary or "")
    to_contractor, to_tenant = _drafts(
        actions, tenant=tenant_name, unit=unit_label, phone=tenant_phone, issue=issue,
        contractor=contractor.display_name if contractor else "",
    )  # fmt: skip
    dispatched = (
        case.state in (CaseState.waiting_on_third_party, CaseState.closed, CaseState.resolved)
        or any(a.status == ActionStatus.approved for a in actions)
        or any(a.id in batch.approved_action_ids for a in actions)
    )
    contractor_phone, contractor_email = (
        batch.identities_by_person.get(contractor.id, ("", "")) if contractor else ("", "")
    )
    ticket: dict[str, Any] = {
        "id": str(case.id),
        "ticketNumber": f"#{case_ref(case.id)}",
        "issueTitle": issue,
        "unitLabel": unit_label,
        "tenantName": tenant_name,
        "tenantId": str(person.id) if person else "",
        "tenantPhone": tenant_phone,
        "category": category_of(trade),
        "contractorName": contractor.display_name if contractor else "",
        "contractorTrade": trade.title(),
        "contractorPhone": contractor_phone,
        "contractorEmail": contractor_email,
        "urgency": case.urgency.value,
        "status": "dispatched" if dispatched else "pending_approval",
        "slaRemaining": "Dispatched" if dispatched else "",
        "isOverdue": False,
        "poBudgetCap": "",
        "reportedAt": case.opened_at.strftime("%Y-%m-%d %H:%M") if case.opened_at else "",
        "notes": case.summary,
        "originalMessage": batch.inbound_text_by_case.get(case.id) or case.summary,
        "contractorDraft": to_contractor,
        "tenantDraft": to_tenant,
        "source": "linked" if case.brixx_ref else "estateos",
        "channel": "whatsapp" if tenant_phone and "@" not in tenant_phone else "gmail",
        "location": "",
    }
    if edits:  # the owner's persisted display edits win over derived values; unknown keys and blanks are dropped
        ticket.update(
            {k: v for k, v in edits.items() if k in ticket and k not in LOCKED_FIELDS and v not in (None, "")}
        )
    return ticket

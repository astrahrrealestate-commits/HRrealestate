"""BRIXX tickets (`TST_TICKET` in the mirror) as read-only rows of the Maintenance list.

The owner's existing tickets live in BRIXX; until they are cases here they are shown as they are there: title, unit,
tenant (the ticket's relatie), contractor (`DIENSTVERLENERID`), urgency (`INDURGENT`) and a status mapped onto the
list's vocabulary. A BRIXX ticket is never `pending_approval`: approving and dispatching need a case, so it has no
approve/dispatch actions and its edits belong in BRIXX. Units and people are resolved through the directory's
`brixx_ref`, so only what the mapper already knows is named; anything else is an empty string, never a guess.
"""

import html
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.maintenance.live import _drafts, _first_inbound_text, category_of, identity_of
from app.db.brixx_erasure import erased_relatie_ids
from app.db.models import ActionRow, Case, Person, Unit
from app.directory.brixx import columns as col

TICKET, TICKET_PK = "tst_ticket", "tst_ticketid"
TICKET_TYPE, TICKET_TYPE_PK = "typ_tickettype", "typ_tickettypeid"
LOCATION, LOCATION_PK = "tst_ticket_locatie", "tst_ticket_locatieid"
PREFIX = "brixx-"
_DONE = ("AFGEHANDELD", "GESLOTEN", "AFGEROND", "GEANNULEERD")


def _clean_html(raw: str | None) -> str:
    """Strip HTML tags and unescape entities for readable plain text."""
    if not raw:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", " ", raw)
    text = re.sub(r"(?i)</(?:p|div|tr|li|h[1-6])>", " ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def is_brixx_ticket(ticket_id: str) -> bool:
    return ticket_id.lower().startswith(PREFIX)


def status_of(row: col.Row) -> str:
    """completed when closed or handled; dispatched when a contractor is on it; otherwise scheduled."""
    status = str(col.pick(row, ("dmticketstatus",)) or "").upper()
    if col.pick(row, ("datumgesloten",)) is not None or any(done in status for done in _DONE):
        return "completed"
    if "DIENSTVERLENER" in status or col.pick(row, ("dienstverlenerid",)) is not None:
        return "dispatched"
    return "scheduled"


def _benaming(session: Session, table: str, pk: str, company_id: UUID) -> dict[int, str]:
    rows = col.read_mirror(session, table, company_id) or []
    return {
        k: str(name)
        for row in rows
        if (k := col.pick_int(row, (pk,))) is not None and (name := col.pick(row, ("benaming", "omschrijving")))
    }


def _units(session: Session, company_id: UUID) -> dict[str, Unit]:
    rows = session.scalars(select(Unit).where(Unit.company_id == company_id, Unit.brixx_ref.is_not(None)))
    return {row.brixx_ref: row for row in rows if row.brixx_ref}


def _people(session: Session, company_id: UUID) -> dict[str, Person]:
    rows = session.scalars(select(Person).where(Person.company_id == company_id, Person.brixx_ref.is_not(None)))
    return {row.brixx_ref: row for row in rows if row.brixx_ref}


def brixx_tickets(
    session: Session, company_id: UUID, *, open_only: bool = False, contacts: bool = True
) -> list[dict[str, Any]]:
    """The company's live BRIXX tickets, newest first, in the Maintenance list's item shape.

    `open_only` drops completed tickets and `contacts=False` skips the phone and email lookups (one query each per
    ticket): the dashboard needs neither."""
    erased = erased_relatie_ids(session, company_id)  # GDPR: an erased person's tickets are not shown
    rows = [
        row
        for row in col.read_mirror(session, TICKET, company_id) or []
        if not col.is_ended(row)
        and col.pick_int(row, (col.RELATIE_PK,)) not in erased
        and not (open_only and status_of(row) == "completed")
    ]
    if not rows:
        return []
    units, people = _units(session, company_id), _people(session, company_id)
    kinds = _benaming(session, TICKET_TYPE, TICKET_TYPE_PK, company_id)
    places = _benaming(session, LOCATION, LOCATION_PK, company_id)
    cases = session.scalars(select(Case).where(Case.company_id == company_id, Case.brixx_ref.is_not(None))).all()
    linked_cases: dict[str, Case] = {str(c.brixx_ref).lower().removeprefix("brixx-"): c for c in cases if c.brixx_ref}
    rows.sort(key=lambda row: str(col.pick(row, col.CREATED) or ""), reverse=True)
    return [
        _ticket(
            session,
            row,
            units,
            people,
            kinds,
            places,
            contacts=contacts,
            linked_case=linked_cases.get(str(col.pick_int(row, (TICKET_PK,)))),
        )
        for row in rows
    ]


def _ticket(
    session: Session,
    row: col.Row,
    units: dict[str, Unit],
    people: dict[str, Person],
    kinds: dict[int, str],
    places: dict[int, str],
    *,
    contacts: bool = True,
    linked_case: Case | None = None,
) -> dict[str, Any]:
    key = col.pick_int(row, (TICKET_PK,))
    unit = units.get(str(col.pick_int(row, (col.VHE_PK,))))
    tenant = people.get(str(col.pick_int(row, (col.RELATIE_PK,))))
    contractor = people.get(str(col.pick_int(row, ("dienstverlenerid",))))
    title = col.pick_text(row, ("titel", "omschrijving"), 200) or "BRIXX ticket"
    kind = kinds.get(col.pick_int(row, (TICKET_TYPE_PK,)) or -1, "")
    place = places.get(col.pick_int(row, (LOCATION_PK,)) or -1, "")
    reported = col.pick(row, col.CREATED)
    status = status_of(row)
    place_info = f" ({place})" if place else ""
    cleaned_desc = f"{title}{place_info}. Official ticket logged in BRIXX."

    contractor_draft: str | None = None
    tenant_draft: str | None = None
    if linked_case is not None:
        inbound = _first_inbound_text(session, linked_case)
        if inbound and inbound.strip():
            cleaned_desc = inbound.strip()
        actions = list(session.scalars(select(ActionRow).where(ActionRow.case_id == linked_case.id)).all())
        contractor_name = (contractor.display_name or "") if contractor else ""
        tenant_name = (tenant.display_name or "") if tenant else ""
        unit_label = ((unit.label or unit.address) or "") if unit else ""
        phone = identity_of(session, tenant.id, phone=True) if tenant and contacts else ""
        contractor_draft, tenant_draft = _drafts(
            actions,
            tenant=tenant_name,
            unit=unit_label,
            phone=phone,
            issue=title,
            contractor=contractor_name,
        )

    return {
        "id": f"{PREFIX}{key}",
        "ticketNumber": f"BRIXX-{key}",
        "issueTitle": title,
        "unitLabel": (unit.label or unit.address) if unit else "",
        "tenantName": tenant.display_name if tenant else "",
        "tenantId": str(tenant.id) if tenant else "",
        "tenantPhone": identity_of(session, tenant.id, phone=True) if tenant and contacts else "",
        "category": category_of(f"{title} {place} {(contractor.trade or '') if contractor else ''}"),
        "contractorName": contractor.display_name if contractor else "",
        "contractorTrade": ((contractor.trade or "") if contractor else "").title(),
        "contractorPhone": identity_of(session, contractor.id, phone=True) if contractor and contacts else "",
        "contractorEmail": identity_of(session, contractor.id, phone=False) if contractor and contacts else "",
        "urgency": "high" if col.as_int(col.pick(row, ("indurgent",))) == 1 else "normal",
        "status": status,
        "slaRemaining": "Dispatched" if status == "dispatched" else "",
        "isOverdue": False,
        "poBudgetCap": "",
        "reportedAt": reported.strftime("%Y-%m-%d") if hasattr(reported, "strftime") else str(reported or ""),
        "notes": " · ".join(part for part in (f"BRIXX {kind}".strip() if kind else "", place) if part),
        "originalMessage": cleaned_desc,
        "contractorDraft": contractor_draft,
        "tenantDraft": tenant_draft,
        "source": "brixx",
        "channel": "brixx",
        "location": place or "",
    }


MESSAGES, MESSAGES_PK = "tst_ticketbericht", "tst_ticketberichtid"
READ_ONLY = "This ticket comes from BRIXX: change or dispatch it in BRIXX."


def _stamp(value: object) -> str:
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).strftime("%Y-%m-%d %H:%M UTC")
    return str(value or "")


def brixx_history(session: Session, company_id: UUID, ticket_id: str) -> tuple[str, list[dict[str, Any]]] | None:
    """(unit label, events) for one BRIXX ticket of the company: opened, its messages, closed. None if unknown."""
    key = col.as_int(ticket_id.lower().removeprefix(PREFIX))
    erased = erased_relatie_ids(session, company_id)
    rows = [
        r
        for r in col.read_mirror(session, TICKET, company_id) or []
        if col.pick_int(r, (col.RELATIE_PK,)) not in erased
    ]
    row = next((r for r in rows if key is not None and col.pick_int(r, (TICKET_PK,)) == key), None)
    if row is None:
        return None
    unit = _units(session, company_id).get(str(col.pick_int(row, (col.VHE_PK,))))
    events = [_event(f"{ticket_id}-open", col.pick(row, col.CREATED), "Ticket opened in BRIXX",
                     col.pick_text(row, ("titel",), 500) or "")]  # fmt: skip
    for message in col.read_mirror(session, MESSAGES, company_id) or []:
        if (
            col.pick_int(message, (TICKET_PK,)) == key
            and not col.is_ended(message)
            and col.pick_int(message, (col.RELATIE_PK,)) not in erased
        ):
            when = col.pick(message, ("actiedatum",)) or col.pick(message, col.CREATED)
            text = col.pick_text(message, ("bericht",), 2000) or ""
            cleaned = _clean_html(text)
            msg_id = f"brixx-msg-{col.pick_int(message, (MESSAGES_PK,))}"
            events.append(_event(msg_id, when, "Message in BRIXX", cleaned))
    if (closed := col.pick(row, ("datumgesloten",))) is not None:
        events.append(_event(f"{ticket_id}-closed", closed, "Ticket closed in BRIXX", ""))
    events.sort(key=lambda e: e["timestamp"])
    return ((unit.label or unit.address or "") if unit else "", events)


def _event(event_id: str, when: object, title: str, description: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "timestamp": _stamp(when),
        "category": "message" if title.startswith("Message") else "audit",
        "actor": "BRIXX",
        "actorType": "system",
        "title": title,
        "description": description,
        "badge": "BRIXX",
    }

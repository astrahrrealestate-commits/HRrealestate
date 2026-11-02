"""Seed rows for the finance repository and snapshot service tests (committed: the service opens its own sessions)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts import ActionType, Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import ActionStatus, LinkMethod, PersonKind, RateSource
from app.db.models import ActionRow, Case, CaseLink, MessageRow, Person, RawEvent, VendorRate

DECIDED = date(2026, 10, 15)
SENT_AT = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
SUMMARY = "Cv ketel onderhoud nodig."
MESSAGES = ("Lekkage herstel 2 uur.",)


@dataclass(frozen=True)
class Seeded:
    company_id: UUID
    case_id: UUID
    action_id: UUID
    vendor_id: UUID
    message_id: UUID


def person(s: Session, company_id: UUID, name: str) -> UUID:
    row = Person(company_id=company_id, kind=PersonKind.contractor, display_name=name, valid_from=date(2025, 1, 1))
    s.add(row)
    s.flush()
    return row.id


def rate(s: Session, company_id: UUID, person_id: UUID, item: str, amount: str, *, unit: str = "hour") -> VendorRate:
    row = VendorRate(
        company_id=company_id, person_id=person_id, item_key=item, description=item, unit=unit,
        amount=Decimal(amount), currency="EUR", source=RateSource.owner, valid_from=date(2026, 1, 1),
    )  # fmt: skip
    s.add(row)
    s.flush()
    return row


def message(s: Session, company_id: UUID, case_id: UUID, text: str) -> UUID:
    raw = RawEvent(company_id=company_id, provider=Channel.whatsapp, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(
        company_id=company_id, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=raw.provider_msg_id,
        thread_ref="thr-fin", sender_identity="+31612345678", direction=Direction.inbound, sent_at=SENT_AT, text=text,
        meta={},
    )  # fmt: skip
    s.add(msg)
    s.flush()
    s.add(CaseLink(company_id=company_id, case_id=case_id, message_id=msg.id, method=LinkMethod.thread))
    return msg.id


def action(
    s: Session, company_id: UUID, case_id: UUID, vendor_id: UUID, kind: ActionType = ActionType.request_contractor
) -> UUID:
    row = ActionRow(
        company_id=company_id, case_id=case_id, type=kind, rationale="test", context_ref=[],
        payload={"kind": kind.value, "contractor_person_id": str(vendor_id), "text": "Kunt u langskomen?"},
        status=ActionStatus.approved,
    )  # fmt: skip
    s.add(row)
    s.flush()
    return row.id


def seed_case(s: Session, company_id: UUID, *, summary: str = SUMMARY, texts: tuple[str, ...] = MESSAGES) -> Seeded:
    """A maintenance case with linked messages and an approved request_contractor action for a new vendor."""
    case = Case(company_id=company_id, category=Category.maintenance, urgency=Urgency.normal, summary=summary)
    s.add(case)
    s.flush()
    vendor = person(s, company_id, "Vendor BV")
    first = [message(s, company_id, case.id, text) for text in texts]
    return Seeded(company_id, case.id, action(s, company_id, case.id, vendor), vendor, first[0])

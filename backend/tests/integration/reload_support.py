"""Seed helpers for the mailbox reload tests (M13 T1/T2): a company with a mailbox, Gmail and WhatsApp mail."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import LinkMethod, PersonKind, PipelineStatus
from app.db.models import (
    Case,
    CaseLink,
    ChannelAccount,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    UnderstandingRow,
)

MAILBOX = "info@reload.test"
HARJOT = "harjot@reload.test"
NOW = datetime.now(UTC).replace(microsecond=0)


@dataclass(frozen=True)
class Mail:
    message_id: UUID
    raw_id: UUID


def connect(engine: Engine, company_id: UUID, mailbox: str = MAILBOX, phone: str = "+31600009999") -> None:
    with Session(engine) as s, s.begin():
        s.add(ChannelAccount(company_id=company_id, channel=Channel.gmail, address=mailbox))
        s.add(OwnerAccount(company_id=company_id, display_name="Harjot", whatsapp_e164=phone, email=HARJOT))


def person(engine: Engine, company_id: UUID, name: str = "Sanne", kind: PersonKind = PersonKind.tenant) -> UUID:
    with Session(engine) as s, s.begin():
        row = Person(company_id=company_id, kind=kind, display_name=name, valid_from=date(2025, 1, 1))
        s.add(row)
        s.flush()
        return row.id


def understanding_body(*, requires_reply: bool = True, category: Category = Category.maintenance,
                       research: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "category": category.value, "intent": "Leak", "urgency": "normal", "requires_reply": requires_reply,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": {"flag": False, "reason": None}, "confidence": 0.9, "sender_role": None,
        "needs_research": bool(research), "research_questions": research or [], "prompt_version": "understanding/v4",
    }  # fmt: skip


def mail(
    engine: Engine,
    company_id: UUID,
    *,
    text: str = "Er lekt water in de badkamer.",
    at: datetime = NOW,
    sender: str = "sanne@reload.test",
    thread: str = "thr-1",
    direction: Direction = Direction.inbound,
    channel: Channel = Channel.gmail,
    mailbox: str | None = MAILBOX,
    person_id: UUID | None = None,
    case_id: UUID | None = None,
    meta: dict[str, Any] | None = None,
    understood: dict[str, Any] | None = None,
    status: PipelineStatus = PipelineStatus.done,
) -> Mail:
    """One stored message (with its raw event), linked to `case_id` and understood with `understood` when given."""
    box = {"mailbox": mailbox} if channel is Channel.gmail and mailbox else {}
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=company_id, provider=channel, provider_msg_id=str(new_id()), payload=box)
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=company_id, raw_event_id=raw.id, channel=channel, provider_msg_id=raw.provider_msg_id,
            thread_ref=thread, sender_identity=sender if direction is Direction.inbound else (mailbox or sender),
            direction=direction, sent_at=at, text=text, person_id=person_id, meta={**box, **(meta or {})},
            pipeline_status=status,
        )  # fmt: skip
        s.add(msg)
        s.flush()
        if case_id is not None:
            s.add(CaseLink(company_id=company_id, case_id=case_id, message_id=msg.id, method=LinkMethod.thread))
        if understood is not None:
            s.add(
                UnderstandingRow(
                    company_id=company_id,
                    message_id=msg.id,
                    category=Category(understood["category"]),
                    urgency=Urgency.normal,
                    body=understood,
                    prompt_version="understanding/v4",
                )
            )
        return Mail(msg.id, raw.id)


def case(engine: Engine, company_id: UUID, person_id: UUID | None, category: Category = Category.maintenance) -> UUID:
    with Session(engine) as s, s.begin():
        row = Case(company_id=company_id, primary_person_id=person_id, category=category, urgency=Urgency.normal,
                   opened_at=NOW - timedelta(days=100))  # fmt: skip
        s.add(row)
        s.flush()
        return row.id

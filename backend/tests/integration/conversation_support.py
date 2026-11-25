"""Seed helpers for the dossier and person-memory tests: people, mails, cases and documents in one company."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.db.enums import ExtractionStatus, LinkMethod, PersonKind
from app.db.models import AttachmentRow, ChannelIdentity, MessageRow, OwnerAccount, Person, RawEvent
from app.pipeline import case_repo

NOW = datetime.now(UTC).replace(microsecond=0)
OWNER = "harjot@hrre.test"
INBOX = "info@hrre.test"


def add_owner(engine: Engine, cid: UUID) -> None:
    with Session(engine) as s, s.begin():
        s.add(OwnerAccount(company_id=cid, display_name="Harjot", whatsapp_e164="+31600000001", email=OWNER))


def add_person(engine: Engine, cid: UUID, name: str, email: str, kind: PersonKind = PersonKind.tenant) -> UUID:
    with Session(engine) as s, s.begin():
        p = Person(company_id=cid, kind=kind, display_name=name, valid_from=date(2026, 1, 1))
        s.add(p)
        s.flush()
        s.add(ChannelIdentity(company_id=cid, person_id=p.id, channel=Channel.gmail, identity=email,
                              valid_from=date(2026, 1, 1)))  # fmt: skip
        return p.id


def add_case(engine: Engine, cid: UUID, person_id: UUID, category: Category = Category.maintenance) -> UUID:
    with Session(engine) as s, s.begin():
        return case_repo.create_case(s, cid, person_id, category, Urgency.normal)


def add_mail(
    engine: Engine, cid: UUID, text: str, *, sender: str, person_id: UUID | None = None, case_id: UUID | None = None,
    thread: str = "t1", days_ago: float = 0, outbound_to: list[str] | None = None, **meta: Any,
) -> UUID:  # fmt: skip
    outbound = outbound_to is not None
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
            thread_ref=thread, sender_identity=INBOX if outbound else sender, person_id=None if outbound else person_id,
            direction=Direction.outbound if outbound else Direction.inbound, sent_at=NOW - timedelta(days=days_ago),
            text=text, meta={"subject": "Lekkage", "to": outbound_to or [INBOX], **meta},
        )  # fmt: skip
        s.add(msg)
        s.flush()
        if case_id is not None:
            case_repo.link_message(s, cid, case_id, msg.id, LinkMethod.thread, None)
        return msg.id


def add_attachment(engine: Engine, cid: UUID, message_id: UUID, filename: str, text: str | None) -> UUID:
    with Session(engine) as s, s.begin():
        row = AttachmentRow(
            company_id=cid, message_id=message_id, s3_key="k", mime_type="application/pdf", filename=filename,
            size_bytes=9, sha256="0" * 64, extracted_text=text,
            extraction_status=ExtractionStatus.done if text else None,
        )  # fmt: skip
        s.add(row)
        s.flush()
        return row.id

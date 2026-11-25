"""A WhatsApp chat that only lives in Chats (`pipeline_status = skipped`, ADR 0015) never reaches the case world:
the inbox, page memory and message search ignore it, while the Chats page and the sender still see every message."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.contracts.thread_key import encode_thread_key
from app.db.enums import PipelineStatus, RawEventStatus
from app.db.models import Company, MessageRow, RawEvent
from app.pipeline.chat_repo import chat_list, chat_messages
from app.pipeline.page_memory import thread_conversation
from app.pipeline.read_repo import inbox_page, thread_messages
from app.tools.message_rag.gate import should_index_message

pytestmark = pytest.mark.integration
KNOWN, STRANGER = "+31611111111", "+31622222222"
NOW = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def _row(db: Session, company: Company, number: str, status: PipelineStatus, text: str = "hallo") -> MessageRow:
    raw = RawEvent(
        company_id=company.id,
        provider=Channel.whatsapp,
        provider_msg_id=f"wamid.{uuid4().hex}",
        payload={},
        status=RawEventStatus.processed,
    )
    db.add(raw)
    db.flush()
    row = MessageRow(
        company_id=company.id,
        raw_event_id=raw.id,
        channel=Channel.whatsapp,
        provider_msg_id=raw.provider_msg_id,
        thread_ref=number,
        sender_identity=number,
        direction=Direction.inbound,
        sent_at=NOW,
        text=text,
        meta={"type": "text"},
        pipeline_status=status,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def chats(db: Session, company: Company) -> tuple[MessageRow, MessageRow]:
    return (
        _row(db, company, KNOWN, PipelineStatus.pending, "de kraan lekt"),
        _row(db, company, STRANGER, PipelineStatus.skipped, "kraan lekt ook bij mij thuis"),
    )


def test_chats_show_both_the_known_contact_and_the_stranger(db: Session, company: Company, chats: object) -> None:
    assert {c.chat_key for c in chat_list(db, company.id, before=None, limit=10)} == {KNOWN, STRANGER}
    assert [m.text for m in chat_messages(db, company.id, STRANGER, before=None, limit=10)] == [
        "kraan lekt ook bij mij thuis"
    ]


def test_the_inbox_lists_only_the_known_contact(db: Session, company: Company, chats: object) -> None:
    keys = {t.thread_key for t in inbox_page(db, company.id, before=None, limit=10)}
    assert keys == {encode_thread_key(Channel.whatsapp, KNOWN)}
    assert thread_messages(db, company.id, encode_thread_key(Channel.whatsapp, STRANGER)) == []


def test_page_memory_never_reads_a_chat_only_thread(db: Session, company: Company, chats: object) -> None:
    known, _ = thread_conversation(db, company.id, Channel.whatsapp, KNOWN)
    stranger, ids = thread_conversation(db, company.id, Channel.whatsapp, STRANGER)
    assert known is not None
    assert (stranger, ids) == (None, [])


def test_chat_only_messages_are_never_indexed_for_search(chats: tuple[MessageRow, MessageRow]) -> None:
    known, stranger = chats
    assert should_index_message(known)[0] is True
    assert should_index_message(stranger) == (False, "chat_only")


def test_the_read_only_sql_role_never_sees_a_chat_only_message(db: Session, company: Company, chats: object) -> None:
    """The custom query agent reads `messages` as `estateos_readonly`; Chats-only rows are hidden from that role."""
    count = text("SELECT count(*) FROM messages WHERE company_id = :c")
    assert db.scalar(count, {"c": company.id}) == 2
    db.execute(text("SET LOCAL ROLE estateos_readonly"))
    try:
        assert db.scalar(count, {"c": company.id}) == 1
        assert db.scalar(text("SELECT count(*) FROM v_message_stats WHERE company_id = :c"), {"c": company.id}) == 1
    finally:
        db.execute(text("RESET ROLE"))


def test_erasing_a_person_also_erases_their_chat_only_messages(db: Session, company: Company) -> None:
    """Chats-only rows never got a person, so an erasure finds them by the person's WhatsApp number."""
    from datetime import date

    from app.db.enums import PersonKind
    from app.db.models import ChannelIdentity, Person
    from app.pipeline.gdpr import erase_person

    person = Person(company_id=company.id, kind=PersonKind.other, display_name="Z", valid_from=date(2026, 1, 1))
    db.add(person)
    db.flush()
    db.add(
        ChannelIdentity(
            company_id=company.id,
            person_id=person.id,
            channel=Channel.whatsapp,
            identity=STRANGER,
            valid_from=date(2026, 1, 1),
        )
    )
    mine = _row(db, company, STRANGER, PipelineStatus.skipped, "mijn privé bericht")
    other = _row(db, company, KNOWN, PipelineStatus.pending, "andermans bericht")
    erase_person(db, company.id, person.id)
    db.refresh(mine)
    db.refresh(other)
    assert mine.text == "[Content erased per GDPR request]"
    assert other.text == "andermans bericht"

"""WhatsApp Chats read queries against real Postgres: grouping, unread, filters, search, paging, scoping."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.db.enums import ActionStatus, DeliveryStatus, LinkMethod, PersonKind
from app.db.models import ActionRow, Case, CaseLink, ChannelIdentity, ChatRead, Company, Person
from app.db.models.ingestion import MessageRow, RawEvent
from app.pipeline import chat_repo
from app.pipeline.chat_repo import BadChatKeyError

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 1, tzinfo=UTC)
TINA = "+31612345678"
BOB = "+31687654321"
STRANGER = "+31611111111"


def _msg(s: Session, cid: UUID, number: str, n: int, **kw: Any) -> MessageRow:
    """WhatsApp row of chat `number` at minute `n`; `created_at` follows `sent_at` so unread cut-offs are testable."""
    pid = f"{number}-{n}-{kw.get('direction', 'in')}"
    raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=pid, payload={})
    s.add(raw)
    s.flush()
    when = T0 + timedelta(minutes=n)
    fields: dict[str, Any] = {
        "direction": Direction.inbound,
        "sender_identity": number,
        "sent_at": when,
        "created_at": when,
        "text": f"m{n}",
    }
    fields.update(kw)
    row = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=pid, thread_ref=number, **fields
    )
    s.add(row)
    s.flush()
    return row


def _person(s: Session, cid: UUID, name: str, kind: PersonKind, number: str) -> Person:
    person = Person(company_id=cid, kind=kind, display_name=name, valid_from=date(2026, 1, 1))
    s.add(person)
    s.flush()
    s.add(
        ChannelIdentity(
            company_id=cid, person_id=person.id, channel=Channel.whatsapp, identity=number, valid_from=date(2026, 1, 1)
        )
    )
    s.flush()
    return person


def _list(
    s: Session, cid: UUID, *, filter: chat_repo.ChatFilter = "all", q: str | None = None
) -> list[chat_repo.ChatSummary]:
    return chat_repo.chat_list(s, cid, before=None, limit=50, filter=filter, q=q)


def _keys(s: Session, cid: UUID, *, filter: chat_repo.ChatFilter = "all", q: str | None = None) -> list[str]:
    return [c.chat_key for c in _list(s, cid, filter=filter, q=q)]


def test_chat_list_groups_by_number_newest_first(db: Session, company: Company) -> None:
    _msg(db, company.id, TINA, 1)
    last_tina = _msg(db, company.id, TINA, 5)
    last_bob = _msg(db, company.id, BOB, 3)
    chats = _list(db, company.id)
    assert [c.chat_key for c in chats] == [TINA, BOB]
    assert chats[0].last_message_id == last_tina.id
    assert chats[0].last_text == "m5"
    assert chats[0].last_at == last_tina.sent_at
    assert chats[0].last_direction == Direction.inbound
    assert chats[1].last_message_id == last_bob.id
    older = chat_repo.chat_list(db, company.id, before=(last_tina.sent_at, last_tina.id), limit=50)
    assert [c.chat_key for c in older] == [BOB]


def test_unread_counts_only_inbound_after_last_read(db: Session, company: Company) -> None:
    for n in (1, 2, 3):
        _msg(db, company.id, TINA, n)
    assert _list(db, company.id)[0].unread == 3
    chat_repo.mark_read(db, company.id, TINA, T0 + timedelta(minutes=2))
    assert _list(db, company.id)[0].unread == 1
    chat_repo.mark_read(db, company.id, TINA, T0 + timedelta(minutes=10))
    assert _list(db, company.id)[0].unread == 0


def test_outbound_and_echo_never_unread(db: Session, company: Company) -> None:
    _msg(db, company.id, TINA, 1, direction=Direction.outbound, sender_identity="+31600000000")
    _msg(db, company.id, TINA, 2, direction=Direction.outbound, delivery_status=DeliveryStatus.delivered)
    chat = _list(db, company.id)[0]
    assert chat.unread == 0
    assert chat.last_direction == Direction.outbound
    assert chat.last_delivery == DeliveryStatus.delivered


def test_name_from_current_identity_unknown_number_is_none(db: Session, company: Company) -> None:
    _person(db, company.id, "Tina Tenant", PersonKind.tenant, TINA)
    _msg(db, company.id, TINA, 1)
    _msg(db, company.id, STRANGER, 2)
    by_key = {c.chat_key: c for c in _list(db, company.id)}
    assert by_key[TINA].name == "Tina Tenant"
    assert by_key[TINA].person_kind == PersonKind.tenant
    assert by_key[STRANGER].name is None
    assert by_key[STRANGER].person_kind is None


def test_filter_tenants_and_contractors_and_unread(db: Session, company: Company) -> None:
    _person(db, company.id, "Tina Tenant", PersonKind.tenant, TINA)
    _person(db, company.id, "Bob Builder", PersonKind.contractor, BOB)
    _msg(db, company.id, TINA, 1)
    _msg(db, company.id, BOB, 2)
    _msg(db, company.id, STRANGER, 3)
    chat_repo.mark_read(db, company.id, BOB, T0 + timedelta(minutes=30))
    assert _keys(db, company.id, filter="tenants") == [TINA]
    assert _keys(db, company.id, filter="contractors") == [BOB]
    assert _keys(db, company.id, filter="unread") == [STRANGER, TINA]
    assert _keys(db, company.id) == [STRANGER, BOB, TINA]


def test_search_matches_name_number_and_text_and_escapes_wildcards(db: Session, company: Company) -> None:
    _person(db, company.id, "Tina Tenant", PersonKind.tenant, TINA)
    _msg(db, company.id, TINA, 1, text="hello")
    _msg(db, company.id, BOB, 2, text="the boiler is leaking")
    _msg(db, company.id, STRANGER, 3, text="we owe 50% extra")

    def keys(q: str) -> list[str]:
        return _keys(db, company.id, q=q)

    assert keys("tina") == [TINA]
    assert keys("87654") == [BOB]
    assert keys("BOILER") == [BOB]
    assert keys("%") == [STRANGER]
    assert keys("_") == []
    assert keys("nothing") == []


def test_empty_text_voice_note_keeps_kind(db: Session, company: Company) -> None:
    _msg(db, company.id, TINA, 1, text="", meta={"type": "audio"})
    chat = _list(db, company.id)[0]
    assert chat.last_text == ""
    assert chat.last_kind == "audio"


def test_other_company_never_listed_and_messages_empty(db: Session, company: Company) -> None:
    other = Company(name="Other")
    db.add(other)
    db.flush()
    _msg(db, other.id, TINA, 1)
    _person(db, other.id, "Foreign Tina", PersonKind.tenant, TINA)
    assert _list(db, company.id) == []
    assert chat_repo.chat_messages(db, company.id, TINA, before=None, limit=10) == []
    assert chat_repo.latest_inbound(db, company.id, TINA) is None
    assert chat_repo.latest_case_id(db, company.id, TINA) is None
    assert [c.chat_key for c in _list(db, other.id)] == [TINA]


def test_chat_messages_pages_oldest_first(db: Session, company: Company) -> None:
    rows = [_msg(db, company.id, TINA, n) for n in range(1, 6)]
    _msg(db, company.id, BOB, 9)
    newest = chat_repo.chat_messages(db, company.id, TINA, before=None, limit=2)
    assert [m.id for m in newest] == [rows[3].id, rows[4].id]
    older = chat_repo.chat_messages(db, company.id, TINA, before=(rows[3].sent_at, rows[3].id), limit=2)
    assert [m.id for m in older] == [rows[1].id, rows[2].id]


def test_mark_read_never_moves_backwards(db: Session, company: Company) -> None:
    chat_repo.mark_read(db, company.id, TINA, T0 + timedelta(hours=2))
    chat_repo.mark_read(db, company.id, TINA, T0 + timedelta(hours=1))
    db.expire_all()
    marks = db.query(ChatRead).filter_by(company_id=company.id, chat_key=TINA).all()
    assert [m.last_read_at for m in marks] == [T0 + timedelta(hours=2)]


def test_parse_chat_key_rejects_email_and_garbage() -> None:
    assert chat_repo.parse_chat_key("+31 6 12345678") == "+31612345678"
    assert chat_repo.parse_chat_key("31612345678") == "+31612345678"
    for bad in ("tina@example.test", "", "abc", "users/123", "+31612345678; drop"):
        with pytest.raises(BadChatKeyError):
            chat_repo.parse_chat_key(bad)


def _case_with_draft(s: Session, cid: UUID, msg: MessageRow, status: ActionStatus, variants: list[object]) -> ActionRow:
    case = Case(company_id=cid, category=Category.other, urgency=Urgency.normal, state=CaseState.open)
    s.add(case)
    s.flush()
    if s.query(CaseLink).filter_by(message_id=msg.id).first() is None:
        s.add(CaseLink(company_id=cid, case_id=case.id, message_id=msg.id, method=LinkMethod.thread))
    action = ActionRow(
        company_id=cid, case_id=case.id, type=ActionType.reply_draft, payload={"body_variants": variants},
        rationale="r", context_ref=[msg.id], status=status,
    )  # fmt: skip
    s.add(action)
    s.flush()
    return action


def test_suggestions_returns_open_reply_draft_variants(db: Session, company: Company) -> None:
    _msg(db, company.id, TINA, 1)
    inbound = _msg(db, company.id, TINA, 2)
    _msg(db, company.id, TINA, 3, direction=Direction.outbound)
    assert chat_repo.latest_inbound(db, company.id, TINA) == inbound
    assert chat_repo.suggestions(db, company.id, TINA) == (None, [])
    rejected = _case_with_draft(db, company.id, inbound, ActionStatus.rejected, ["old"])
    assert chat_repo.suggestions(db, company.id, TINA) == (None, [])
    action = _case_with_draft(db, company.id, inbound, ActionStatus.pending_approval, ["a", "", 7, "b", "c", "d"])
    assert chat_repo.suggestions(db, company.id, TINA) == (action.id, ["a", "b", "c"])
    assert chat_repo.latest_case_id(db, company.id, TINA) == rejected.case_id  # linked via the first case
    assert chat_repo.suggestions(db, company.id, BOB) == (None, [])

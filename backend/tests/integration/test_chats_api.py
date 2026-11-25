"""`/api/chats` against real Postgres: company scoping, paging errors, identical 404s, attachments, quotes, read."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.db.enums import DeliveryStatus, LinkMethod, PersonKind, PipelineStatus
from app.db.models import (
    AllowedUser,
    Case,
    CaseLink,
    ChannelIdentity,
    ChatRead,
    Company,
    OwnerAccount,
    Person,
    UnderstandingRow,
)
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.main import create_app
from app.storage.memory import MemoryStorage
from app.storage.ports import MAX_PRESIGN_TTL_S
from tests.integration.access_support import CSRF, add_person_to_team

pytestmark = pytest.mark.integration
T0 = datetime(2026, 11, 1, tzinfo=UTC)
TINA = "+31612345678"
BOB = "+31687654321"
ONLY_B = "+31622222222"
UNKNOWN = "+31699999999"
NOT_FOUND = {"detail": "chat not found"}


@dataclass
class World:
    client: TestClient
    app: Any
    settings: Settings
    engine: Engine
    cid: UUID
    tina_ids: list[UUID]
    case_id: UUID


def _msg(s: Session, cid: UUID, number: str, n: int, **kw: Any) -> MessageRow:
    direction = kw.get("direction", Direction.inbound)
    pid = kw.pop("pid", f"{cid.hex[:6]}-{number}-{n}-{direction}")
    raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=pid, payload={})
    s.add(raw)
    s.flush()
    fields: dict[str, Any] = {
        "direction": Direction.inbound,
        "sender_identity": number,
        "sent_at": T0 + timedelta(minutes=n),
        "text": f"m{n}",
    }
    fields.update(kw)
    row = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=pid, thread_ref=number, **fields
    )
    s.add(row)
    s.flush()
    return row


def _attachment(s: Session, cid: UUID, message_id: UUID, name: str, key: str, mime: str = "image/jpeg") -> None:
    s.add(
        AttachmentRow(
            company_id=cid, message_id=message_id, s3_key=key, mime_type=mime, filename=name,
            size_bytes=3, sha256="ab" * 32,
        )
    )  # fmt: skip


def _seed_a(s: Session, a: Company) -> tuple[list[MessageRow], UUID]:
    t1 = _msg(s, a.id, TINA, 1, pid="wamid.t1", text="first")
    t2 = _msg(s, a.id, TINA, 2, direction=Direction.outbound, delivery_status=DeliveryStatus.sent,
              meta={"reply_to": "wamid.t1"})  # fmt: skip
    t3 = _msg(
        s, a.id, TINA, 3, pipeline_status=PipelineStatus.pending, meta={"type": "image", "reply_to": "wamid.bonly"}
    )
    t4 = _msg(s, a.id, TINA, 4, direction=Direction.outbound, meta={"send_error": "window closed"},
              delivery_status=DeliveryStatus.failed)  # fmt: skip
    t5 = _msg(s, a.id, TINA, 5, direction=Direction.outbound,
              meta={"reply_to": "wamid.bob1", "client_msg_id": "c-5"})  # our send path: queued, no status  # fmt: skip
    t6 = _msg(s, a.id, TINA, 6, direction=Direction.outbound, meta={"echo": True})  # Business-app echo, no status
    _msg(s, a.id, BOB, 7, pid="wamid.bob1", text="boiler")
    body = {"suspicious": {"flag": True, "reason": "r" * 300}}
    s.add(UnderstandingRow(company_id=a.id, message_id=t3.id, category=Category.administration, urgency=Urgency.normal,
                           body=body, prompt_version="v1"))  # fmt: skip
    _attachment(s, a.id, t3.id, "p.jpg", "media/a/ab/abc")
    person = Person(company_id=a.id, kind=PersonKind.tenant, display_name="Tina Tenant", valid_from=date(2026, 1, 1))
    s.add(person)
    s.flush()
    s.add(ChannelIdentity(company_id=a.id, person_id=person.id, channel=Channel.whatsapp, identity=TINA,
                          valid_from=date(2026, 1, 1)))  # fmt: skip
    case = Case(company_id=a.id, category=Category.administration, urgency=Urgency.normal, state=CaseState.open)
    s.add(case)
    s.flush()
    s.add(CaseLink(company_id=a.id, case_id=case.id, message_id=t3.id, method=LinkMethod.thread))
    return [t1, t2, t3, t4, t5, t6], case.id


def _seed_b(s: Session, b: Company, leak_into: UUID) -> None:
    bmsg = _msg(s, b.id, TINA, 9, pid="wamid.bonly", text="b secret")  # the same number is a different chat in B
    _msg(s, b.id, ONLY_B, 10)
    _attachment(s, b.id, bmsg.id, "b-secret.png", "media/b/cd/cde")
    _attachment(s, b.id, leak_into, "leak.png", "media/b/ef/efg")  # B row that points at one of A's messages


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.flush()
        owner = OwnerAccount(company_id=a.id, display_name="H", whatsapp_e164="+31699999998", email="h@a.test")
        s.add(owner)
        msgs, case_id = _seed_a(s, a)
        _seed_b(s, b, leak_into=msgs[0].id)
        s.commit()
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        settings = Settings(
            database_url=pg_url,  # type: ignore[arg-type]
            env="test",
            dashboard_session_secret=SecretStr("x" * 32),
            _env_file=None,
        )
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock(), storage=MemoryStorage())
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, app, settings, migrated_engine, a.id, [m.id for m in msgs], case_id)
        ids = [a.id, b.id]
        s.query(CaseLink).filter(CaseLink.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(ChannelIdentity).filter(ChannelIdentity.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(AllowedUser).filter(AllowedUser.company_id.in_(ids)).delete(synchronize_session=False)
        for model in (AttachmentRow, UnderstandingRow, ChatRead, MessageRow, Case, Person, RawEvent):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(OwnerAccount).filter(OwnerAccount.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def _messages(world: World, key: str = TINA) -> list[dict[str, Any]]:
    response = world.client.get(f"/api/chats/{key}/messages")
    assert response.status_code == 200
    return list(response.json()["messages"])


def test_list_is_company_scoped_and_newest_first(world: World) -> None:
    body = world.client.get("/api/chats").json()
    assert [c["chat_key"] for c in body] == [BOB, TINA]  # ONLY_B belongs to the other company
    tina = body[1]
    assert tina["name"] == "Tina Tenant"
    assert tina["person_kind"] == "tenant"
    assert tina["last_direction"] == "outbound"
    assert (tina["last_delivery"], tina["last_pending"]) == (None, False)  # the newest Tina row is an echo
    assert tina["unread"] == 2
    stamp, _, last_id = tina["cursor"].partition("|")
    assert last_id == tina["last_message_id"]
    assert datetime.fromisoformat(stamp) == datetime.fromisoformat(tina["last_at"])
    paged = world.client.get("/api/chats", params={"limit": 1, "before": body[0]["cursor"]}).json()
    assert [c["chat_key"] for c in paged] == [TINA]
    assert [c["chat_key"] for c in world.client.get("/api/chats", params={"filter": "tenants"}).json()] == [TINA]
    assert [c["chat_key"] for c in world.client.get("/api/chats", params={"q": "  boiler "}).json()] == [BOB]
    assert len(world.client.get("/api/chats", params={"q": "  "}).json()) == 2  # blank search is no filter


def test_limit_above_100_is_422(world: World) -> None:
    assert world.client.get("/api/chats", params={"limit": 101}).status_code == 422
    assert world.client.get("/api/chats", params={"limit": 0}).status_code == 422
    assert world.client.get(f"/api/chats/{TINA}/messages", params={"limit": 201}).status_code == 422
    assert world.client.get("/api/chats", params={"q": "x" * 101}).status_code == 422


def test_bad_cursor_is_422(world: World) -> None:
    for url in ("/api/chats", f"/api/chats/{TINA}/messages"):
        response = world.client.get(url, params={"before": "garbage"})
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid cursor"}


def test_unknown_malformed_and_foreign_chat_key_give_identical_404(world: World) -> None:
    responses = [world.client.get(f"/api/chats/{key}/messages") for key in (UNKNOWN, "tina@example.test", ONLY_B)]
    responses.append(world.client.post(f"/api/chats/{ONLY_B}/read", headers=CSRF))
    responses.append(world.client.post(f"/api/chats/{UNKNOWN}/read", headers=CSRF))
    responses.append(world.client.post("/api/chats/not-a-number/read", headers=CSRF))
    assert {r.status_code for r in responses} == {404}
    assert all(r.json() == NOT_FOUND for r in responses)
    assert len({r.text for r in responses}) == 1
    with Session(world.engine) as s:  # a refused read must not leave a marker behind
        assert s.query(ChatRead).filter(ChatRead.company_id == world.cid).count() == 0


def test_thread_carries_name_case_and_message_state(world: World) -> None:
    thread = world.client.get(f"/api/chats/{TINA}/messages").json()
    assert (thread["chat_key"], thread["name"], thread["person_kind"]) == (TINA, "Tina Tenant", "tenant")
    assert thread["case_id"] == str(world.case_id)
    messages = thread["messages"]
    assert [m["id"] for m in messages] == [str(i) for i in world.tina_ids]  # oldest first
    sent, failed, queued, echo = messages[1], messages[3], messages[4], messages[5]
    assert (sent["delivery_status"], sent["pending"], sent["error"]) == ("sent", False, None)
    assert (failed["delivery_status"], failed["pending"], failed["error"]) == ("failed", False, "window closed")
    assert (queued["delivery_status"], queued["pending"]) == (None, True)
    assert (echo["delivery_status"], echo["pending"]) == (None, False)  # an echo is not ours to send: shown as sent
    assert messages[0]["pending"] is False  # inbound never pending
    assert messages[2]["kind"] == "image"


def test_messages_paging_before_cursor(world: World) -> None:
    newest = world.client.get(f"/api/chats/{TINA}/messages", params={"limit": 2}).json()["messages"]
    assert [m["id"] for m in newest] == [str(i) for i in world.tina_ids[4:]]
    cursor = f"{newest[0]['sent_at']}|{newest[0]['id']}"
    older = world.client.get(f"/api/chats/{TINA}/messages", params={"limit": 2, "before": cursor}).json()["messages"]
    assert [m["id"] for m in older] == [str(i) for i in world.tina_ids[2:4]]


def test_empty_before_page_is_200_with_the_chat_header(world: World) -> None:
    before_all = {"before": f"{T0.isoformat()}|{world.cid}"}  # older than every message: end of history, not a 404
    response = world.client.get(f"/api/chats/{TINA}/messages", params=before_all)
    assert response.status_code == 200
    body = response.json()
    assert body["messages"] == []
    assert (body["name"], body["person_kind"], body["case_id"]) == ("Tina Tenant", "tenant", str(world.case_id))
    for key in (UNKNOWN, ONLY_B, "tina@example.test"):  # a chat with no messages at all stays the one 404
        assert world.client.get(f"/api/chats/{key}/messages", params=before_all).json() == NOT_FOUND


def test_messages_include_attachment_presigned_url_with_ttl(world: World) -> None:
    attachments = _messages(world)[2]["attachments"]
    assert [a["filename"] for a in attachments] == ["p.jpg"]
    url = attachments[0]["url"]
    assert int(parse_qs(urlparse(url).query)["expires_in"][0]) == MAX_PRESIGN_TTL_S
    assert "media/a/ab/abc" in url


def test_unsafe_attachment_types_get_forced_download_urls(world: World) -> None:
    with Session(world.engine) as s:
        _attachment(s, world.cid, world.tina_ids[0], "page.html", "media/a/11/html", mime="text/html")
        _attachment(s, world.cid, world.tina_ids[0], "logo.svg", "media/a/22/svg", mime="image/svg+xml")
        s.commit()
    by_name = {a["filename"]: a["url"] for a in _messages(world)[0]["attachments"]}
    for name in ("page.html", "logo.svg"):
        query = parse_qs(urlparse(by_name[name]).query)
        assert query["response-content-type"] == ["application/octet-stream"]
        assert query["response-content-disposition"][0].startswith("attachment;")


def test_list_last_pending_follows_the_send_path_rule(world: World) -> None:
    with Session(world.engine) as s:
        _msg(s, world.cid, BOB, 20, direction=Direction.outbound, meta={"client_msg_id": "c-bob"})
        s.commit()
    listed = {c["chat_key"]: c for c in world.client.get("/api/chats").json()}
    assert listed[BOB]["last_pending"] is True
    assert listed[TINA]["last_pending"] is False


def test_messages_do_not_leak_other_company_attachments(world: World) -> None:
    messages = _messages(world)
    names = [a["filename"] for m in messages for a in m["attachments"]]
    assert names == ["p.jpg"]  # B's "leak.png" points at A's first message but belongs to B
    assert "media/b" not in str(messages)


def test_suspicious_and_held_messages_are_returned_with_state(world: World) -> None:
    held = _messages(world)[2]
    assert held["suspicious"] is True
    assert len(held["suspicious_reason"]) == 200
    assert _messages(world)[0]["suspicious"] is False
    assert _messages(world)[0]["suspicious_reason"] is None


def test_quote_resolves_text_from_same_company_only(world: World) -> None:
    messages = _messages(world)
    assert messages[1]["reply_to"] == {"id": str(world.tina_ids[0]), "text": "first"}
    assert messages[2]["reply_to"] is None  # "wamid.bonly" exists only in the other company
    assert messages[0]["reply_to"] is None


def test_quote_of_a_message_in_another_chat_is_not_resolved(world: World) -> None:
    assert _messages(world)[4]["reply_to"] is None  # "wamid.bob1" is Bob's message: a quote stays inside its chat


def test_read_clears_unread_in_list(world: World) -> None:
    listed = {c["chat_key"]: c for c in world.client.get("/api/chats", params={"filter": "unread"}).json()}
    assert listed[TINA]["unread"] == 2
    response = world.client.post(f"/api/chats/{TINA}/read", headers=CSRF)
    assert response.status_code == 204
    assert response.content == b""
    unread = {c["chat_key"]: c["unread"] for c in world.client.get("/api/chats").json()}
    assert unread == {BOB: 1, TINA: 0}
    assert [c["chat_key"] for c in world.client.get("/api/chats", params={"filter": "unread"}).json()] == [BOB]


def test_read_requires_the_client_header(world: World) -> None:
    assert world.client.post(f"/api/chats/{TINA}/read").status_code == 403


def test_unauthenticated_is_401(world: World) -> None:
    with TestClient(world.app) as anonymous:
        assert anonymous.get("/api/chats").status_code == 401
        assert anonymous.get(f"/api/chats/{TINA}/messages").status_code == 401
        assert anonymous.post(f"/api/chats/{TINA}/read", headers=CSRF).status_code == 401


def test_profile_without_inbox_section_is_403(world: World) -> None:
    clerk = add_person_to_team(world.engine, world.cid, "clerk@a.test", role="member", sections=["contacts"])
    with TestClient(world.app) as client:
        client.cookies.set(COOKIE, issue_session(world.settings, clerk, datetime.now(UTC)))
        assert client.get("/api/chats").status_code == 403
        assert client.get(f"/api/chats/{TINA}/messages").status_code == 403
        assert client.post(f"/api/chats/{TINA}/read", headers=CSRF).status_code == 403

"""`POST /api/chats/{key}/messages`, `GET /api/chats/{key}/suggestions` and the composer state against real Postgres:
store first then enqueue, replay safety, recipient and suggestion checks, rate limit, composer states."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.chats import send as send_module
from app.api.v1.auth import COOKIE, Principal, issue_session
from app.api.v1.ratelimit import RateLimiter
from app.contracts import ActionType, CaseState, Category, Channel, Direction, OutboundMode, Urgency
from app.core.workflow_names import CHAT_QUEUE, CHAT_SEND
from app.db.enums import ActionStatus, DeliveryStatus, PersonKind, PipelineStatus, RawEventStatus
from app.db.models import (
    ActionRow,
    AllowedUser,
    Case,
    ChannelAccount,
    ChannelIdentity,
    ChatRead,
    Company,
    OwnerAccount,
    Person,
    UnderstandingRow,
)
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from app.pipeline.understand import requeue_candidates
from app.storage.memory import MemoryStorage
from tests.integration.access_support import CSRF, add_person_to_team, make_settings

pytestmark = pytest.mark.integration
TINA = "+31612345678"
BOB = "+31687654321"  # last wrote 30 h ago: window closed
CARL = "+31644444444"  # a second open chat
ECHO = "+31633333333"  # only ever echoed outbound: nobody to answer
ONLY_B = "+31622222222"
OWNER_NUMBER = "+31699999998"  # the owner's own number: never a chat we may answer
ACCOUNT_NUMBER = "+31655555555"  # a number of one of the company's channel accounts
UNKNOWN = "+31699999999"
NOT_FOUND = {"detail": "chat not found"}
NOW = datetime.now(UTC)


@dataclass
class World:
    client: TestClient
    engine: Engine
    cid: UUID
    other: UUID
    case_id: UUID
    tina_inbound: UUID

    @property
    def enqueue(self) -> MagicMock:
        mock: MagicMock = self.client.app.state.workflow_client.enqueue  # type: ignore[attr-defined]
        return mock


def _msg(s: Session, cid: UUID, number: str, minutes_ago: int, direction: Direction = Direction.inbound) -> MessageRow:
    pid = f"{cid.hex[:6]}-{number}-{minutes_ago}-{direction}"
    raw = RawEvent(
        company_id=cid, provider=Channel.whatsapp, provider_msg_id=pid, payload={}, status=RawEventStatus.processed
    )
    s.add(raw)
    s.flush()
    row = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=pid, thread_ref=number,
        sender_identity=number if direction is Direction.inbound else "echo", direction=direction,
        sent_at=NOW - timedelta(minutes=minutes_ago), text="hello",
    )  # fmt: skip
    s.add(row)
    s.flush()
    return row


def _draft(s: Session, cid: UUID, case_id: UUID, inbound: UUID, status: ActionStatus, **kw: Any) -> UUID:
    action = ActionRow(
        company_id=cid, case_id=case_id, type=kw.get("type", ActionType.reply_draft),
        payload={"body_variants": ["Optie A", "Optie B", "Optie C", "Optie D"]}, rationale="r",
        context_ref=[inbound], status=status,
    )  # fmt: skip
    s.add(action)
    s.flush()
    return action.id


def _case(s: Session, cid: UUID) -> UUID:
    case = Case(company_id=cid, category=Category.other, urgency=Urgency.normal, state=CaseState.open)
    s.add(case)
    s.flush()
    return case.id


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    with Session(migrated_engine) as s:
        a, b = Company(name="A", outbound_mode=OutboundMode.send), Company(name="B", outbound_mode=OutboundMode.send)
        s.add_all([a, b])
        s.flush()
        owner = OwnerAccount(company_id=a.id, display_name="H", whatsapp_e164=OWNER_NUMBER, email="h@a.test")
        s.add(owner)
        tina = _msg(s, a.id, TINA, 60)
        _msg(s, a.id, BOB, 30 * 60)
        _msg(s, a.id, ECHO, 10, Direction.outbound)
        _msg(s, a.id, CARL, 20)
        _msg(s, a.id, OWNER_NUMBER, 5)
        _msg(s, a.id, ACCOUNT_NUMBER, 5)
        s.add(ChannelAccount(company_id=a.id, channel=Channel.whatsapp, address=ACCOUNT_NUMBER))
        _msg(s, b.id, ONLY_B, 5)
        case_id = _case(s, a.id)
        s.commit()
        settings = make_settings(pg_url)
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock(), storage=MemoryStorage())
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(client, migrated_engine, a.id, b.id, case_id, tina.id)
        ids = [a.id, b.id]
        for model in (ActionRow, UnderstandingRow, ChatRead, MessageRow, Case, RawEvent):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        for model in (AllowedUser, ChannelAccount, OwnerAccount, ChannelIdentity, Person):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def _post(world: World, client_msg_id: UUID | str, text: str = "Hallo Tina", key: str = TINA, **extra: Any) -> Any:
    body = {"client_msg_id": str(client_msg_id), "text": text, **extra}
    return world.client.post(f"/api/chats/{key}/messages", json=body, headers=CSRF)


def _rows(world: World, client_msg_id: UUID | str | None = None) -> list[MessageRow]:
    with Session(world.engine) as s:
        stmt = select(MessageRow).where(MessageRow.company_id == world.cid, MessageRow.direction == Direction.outbound)
        stmt = stmt.where(MessageRow.meta["client_msg_id"].as_string().is_not(None))
        if client_msg_id is not None:
            stmt = stmt.where(MessageRow.meta["client_msg_id"].as_string() == str(client_msg_id))
        return list(s.scalars(stmt))


def _composer(world: World, key: str) -> dict[str, Any]:
    response = world.client.get(f"/api/chats/{key}/messages")
    assert response.status_code == 200
    return dict(response.json()["composer"])


def _set_company(world: World, **fields: Any) -> None:
    if not fields:
        return
    with Session(world.engine) as s, s.begin():
        s.query(Company).filter(Company.id == world.cid).update(fields)


def test_send_inserts_pending_row_then_enqueues_with_workflow_id(world: World) -> None:
    cmid = uuid4()
    seen: list[int] = []
    world.enqueue.side_effect = lambda *a, **k: seen.append(len(_rows(world, cmid)))  # the row is committed first
    typed = "  Hallo Tina,\nmorgen 9u ok?  "
    response = _post(world, cmid, typed)
    assert response.status_code == 202
    body = response.json()
    shown = (body["text"], body["direction"], body["pending"], body["delivery_status"])
    assert shown == (typed, "outbound", True, None)
    assert body["client_msg_id"] == str(cmid)
    assert seen == [1]
    options, company, message = world.enqueue.call_args.args
    assert options == {
        "queue_name": CHAT_QUEUE,
        "workflow_name": CHAT_SEND,
        "workflow_id": f"chat:{world.cid}:{cmid}",
    }
    assert (company, message) == (str(world.cid), body["id"])
    (row,) = _rows(world, cmid)
    assert (row.text, row.thread_ref, row.sender_identity, row.channel) == (typed, TINA, "dashboard", Channel.whatsapp)
    stored = (row.delivery_status, row.pipeline_status, row.provider_msg_id)
    assert stored == (None, PipelineStatus.skipped, f"dash:{cmid}")  # Tina is no directory contact: Chats only
    assert row.meta == {"client_msg_id": str(cmid), "type": "text", "dashboard": True}
    with Session(world.engine) as s:
        raw = s.get(RawEvent, row.raw_event_id)
        assert raw is not None
        assert (raw.payload, raw.status) == ({"kind": "dashboard_send"}, "processed")
        assert raw.provider_msg_id == f"dash:{cmid}"


def test_double_post_same_client_msg_id_one_row_one_enqueue_id(world: World) -> None:
    cmid = uuid4()
    first, second = _post(world, cmid), _post(world, cmid)
    assert (first.status_code, second.status_code) == (202, 202)
    assert first.json()["id"] == second.json()["id"]
    assert len(_rows(world, cmid)) == 1
    ids = {call.args[0]["workflow_id"] for call in world.enqueue.call_args_list}
    assert ids == {f"chat:{world.cid}:{cmid}"}  # a replay re-enqueues the same id: DBOS dedupes it


def test_post_again_after_sent_returns_the_same_row(world: World) -> None:
    cmid = uuid4()
    first = _post(world, cmid).json()
    with Session(world.engine) as s, s.begin():  # the sender finished: wamid replaces the placeholder
        s.query(MessageRow).filter(MessageRow.id == UUID(first["id"])).update(
            {"provider_msg_id": "wamid.SENT", "delivery_status": DeliveryStatus.sent}
        )
    again = _post(world, cmid)
    assert again.status_code == 202
    assert again.json()["id"] == first["id"]
    assert (again.json()["delivery_status"], again.json()["pending"]) == ("sent", False)
    assert len(_rows(world, cmid)) == 1


def test_lost_race_integrity_error_rereads_the_winner(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    cmid = uuid4()
    first = _post(world, cmid).json()
    real = send_module.find_by_client_id
    calls: list[int] = []

    def blind_first(session: Session, company_id: UUID, client_msg_id: str) -> MessageRow | None:
        calls.append(1)
        return None if len(calls) == 1 else real(session, company_id, client_msg_id)

    monkeypatch.setattr(send_module, "find_by_client_id", blind_first)
    twin = pytest.raises(IntegrityError)  # the unique indexes really do refuse a second row
    with twin, Session(world.engine) as s, s.begin():
        send_module.insert_pending(s, world.cid, TINA, cmid, "x", None, datetime.now(UTC))
    second = _post(world, cmid)
    assert second.status_code == 202
    assert second.json()["id"] == first["id"]
    assert len(_rows(world, cmid)) == 1


def test_replay_with_different_text_is_409_and_stores_nothing_new(world: World) -> None:
    cmid = uuid4()
    first = _post(world, cmid, "one")
    other = _post(world, cmid, "two")
    assert (other.status_code, other.json()) == (409, {"detail": "client message id already used with different text"})
    assert [r.text for r in _rows(world, cmid)] == ["one"]
    assert _post(world, cmid, "one").json()["id"] == first.json()["id"]


def test_lost_race_to_a_twin_in_another_chat_is_409(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    cmid = uuid4()
    assert _post(world, cmid, key=CARL).status_code == 202
    real = send_module.find_by_client_id
    calls: list[int] = []

    def blind_first(session: Session, company_id: UUID, client_msg_id: str) -> MessageRow | None:
        calls.append(1)
        return None if len(calls) == 1 else real(session, company_id, client_msg_id)

    monkeypatch.setattr(send_module, "find_by_client_id", blind_first)
    response = _post(world, cmid, key=TINA)  # the lookup misses, the insert loses, the winner is CARL's row
    assert (response.status_code, response.json()) == (
        409,
        {"detail": "client message id already used in another chat"},
    )
    assert len(_rows(world, cmid)) == 1


def test_enqueue_failure_keeps_the_pending_row_and_a_repost_recovers(world: World) -> None:
    cmid = uuid4()
    world.enqueue.side_effect = RuntimeError("queue down")
    response = _post(world, cmid)
    assert response.status_code == 202
    assert response.json()["pending"] is True
    assert len(_rows(world, cmid)) == 1
    world.enqueue.side_effect = None
    world.enqueue.reset_mock()
    again = _post(world, cmid)
    assert again.json()["id"] == response.json()["id"]
    assert world.enqueue.call_count == 1


@pytest.mark.parametrize("text", ["", "   \n\t ", "x" * 4097, "a\x00b"])
def test_empty_whitespace_too_long_and_nul_text_are_422(world: World, text: str) -> None:
    assert _post(world, uuid4(), text).status_code == 422
    assert _rows(world) == []
    world.enqueue.assert_not_called()


def test_4096_chars_and_a_non_uuid_client_id(world: World) -> None:
    assert _post(world, uuid4(), "x" * 4096).status_code == 202
    assert _post(world, uuid4(), " " + "x" * 4096).status_code == 422  # the unstripped text is what is sent
    assert _post(world, "not-a-uuid").status_code == 422
    assert _post(world, "c-1; drop").status_code == 422


def test_unknown_foreign_and_malformed_chat_key_are_identical_404_and_never_enqueue(world: World) -> None:
    responses = [_post(world, uuid4(), key=key) for key in (UNKNOWN, ONLY_B, "tina@example.test", "not-a-number")]
    assert {r.status_code for r in responses} == {404}
    assert all(r.json() == NOT_FOUND for r in responses)
    world.enqueue.assert_not_called()
    assert _rows(world) == []


def test_request_cannot_choose_recipient(world: World) -> None:
    response = _post(world, uuid4(), to=BOB)
    assert response.status_code == 422
    assert _post(world, uuid4(), thread_ref=BOB).status_code == 422
    assert _rows(world) == []
    world.enqueue.assert_not_called()


def test_a_client_msg_id_used_in_another_chat_is_409(world: World) -> None:
    cmid = uuid4()
    assert _post(world, cmid, key=TINA).status_code == 202
    assert _post(world, cmid, key=BOB).status_code == 409
    assert len(_rows(world, cmid)) == 1


def test_send_needs_the_client_header_and_a_session(world: World) -> None:
    body = {"client_msg_id": str(uuid4()), "text": "x"}
    assert world.client.post(f"/api/chats/{TINA}/messages", json=body).status_code == 403
    anonymous = TestClient(world.client.app)
    assert anonymous.post(f"/api/chats/{TINA}/messages", json=body, headers=CSRF).status_code == 401
    world.enqueue.assert_not_called()


def test_suggestion_action_must_be_an_open_reply_draft_of_this_chat(world: World) -> None:
    with Session(world.engine) as s, s.begin():
        own = _draft(s, world.cid, world.case_id, world.tina_inbound, ActionStatus.pending_approval)
        closed = _draft(s, world.cid, world.case_id, world.tina_inbound, ActionStatus.rejected)
        wrong_type = _draft(
            s, world.cid, world.case_id, world.tina_inbound, ActionStatus.proposed, type=ActionType.notify_owner
        )
        bob_msg = s.scalars(select(MessageRow).where(MessageRow.thread_ref == BOB)).one()
        elsewhere = _draft(s, world.cid, world.case_id, bob_msg.id, ActionStatus.proposed)
        other_case = _case(s, world.other)
        b_msg = s.scalars(select(MessageRow).where(MessageRow.thread_ref == ONLY_B)).one()
        foreign = _draft(s, world.other, other_case, b_msg.id, ActionStatus.proposed)
    bad = [closed, wrong_type, elsewhere, foreign, uuid4()]
    for action_id in bad:
        response = _post(world, uuid4(), suggestion_action_id=str(action_id))
        assert response.status_code == 422, action_id
    assert _rows(world) == []
    world.enqueue.assert_not_called()
    cmid = uuid4()
    assert _post(world, cmid, suggestion_action_id=str(own)).status_code == 202
    assert _rows(world, cmid)[0].meta["suggestion_action_id"] == str(own)


def test_suggestion_action_of_other_company_is_422(world: World) -> None:
    with Session(world.engine) as s, s.begin():
        b_msg = s.scalars(select(MessageRow).where(MessageRow.thread_ref == ONLY_B)).one()
        foreign = _draft(s, world.other, _case(s, world.other), b_msg.id, ActionStatus.pending_approval)
    assert _post(world, uuid4(), suggestion_action_id=str(foreign)).status_code == 422


def test_composer_state_open_window_closed_draft_mode_paused_no_recipient(world: World) -> None:
    tina = _composer(world, TINA)
    assert tina["state"] == "open"
    closes = datetime.fromisoformat(tina["window_closes_at"])
    assert timedelta(hours=21, minutes=50) < closes - datetime.now(UTC) < timedelta(hours=22, minutes=10)
    assert _composer(world, BOB)["state"] == "window_closed"
    assert _composer(world, ECHO) == {"state": "no_recipient", "window_closes_at": None}
    _set_company(world, outbound_mode=OutboundMode.draft)
    assert _composer(world, TINA)["state"] == "draft_mode"
    _set_company(world, paused=True)
    assert _composer(world, TINA)["state"] == "paused"  # paused outranks draft mode, as the sender's gate order does
    assert _composer(world, ECHO)["state"] == "paused"


def test_send_is_rate_limited_in_its_own_group(world: World) -> None:
    world.client.app.state.rate_limiter = RateLimiter(clock=lambda: 0.0)  # type: ignore[attr-defined]  # no refill
    cmid = uuid4()
    codes = [_post(world, cmid).status_code for _ in range(31)]
    assert codes[:30] == [202] * 30
    assert codes[30] == 429
    decide = world.client.post(f"/api/inbox/approvals/{uuid4()}/decide", json={}, headers=CSRF)
    assert decide.status_code != 429  # exhausting chat sends does not starve the approve/decide bucket


def test_pipeline_does_not_process_dashboard_row(world: World) -> None:
    cmid = uuid4()
    message_id = UUID(_post(world, cmid).json()["id"])
    (row,) = _rows(world, cmid)
    assert (row.pipeline_status, row.pipeline_attempts) == (PipelineStatus.skipped, 0)
    with Session(world.engine) as s:
        understood = select(func.count()).select_from(UnderstandingRow).where(UnderstandingRow.message_id == message_id)
        assert s.scalar(understood) == 0
        raw = s.get(RawEvent, row.raw_event_id)
        assert raw is not None
        assert raw.status is RawEventStatus.processed  # neither `pending` nor retryable `failed`: ingestion skips it
    assert message_id not in {mid for mid, _ in requeue_candidates(world.engine, datetime.now(UTC) + timedelta(days=2))}


def test_suggestions_endpoint_returns_variants_and_none_when_absent(world: World) -> None:
    empty = world.client.get(f"/api/chats/{TINA}/suggestions")
    assert empty.status_code == 200
    assert empty.json() == {"action_id": None, "variants": []}
    with Session(world.engine) as s, s.begin():
        action = _draft(s, world.cid, world.case_id, world.tina_inbound, ActionStatus.pending_approval)
    body = world.client.get(f"/api/chats/{TINA}/suggestions").json()
    assert body == {"action_id": str(action), "variants": ["Optie A", "Optie B", "Optie C"]}
    for key in (UNKNOWN, ONLY_B, "nope"):
        response = world.client.get(f"/api/chats/{key}/suggestions")
        assert (response.status_code, response.json()) == (404, NOT_FOUND)


@pytest.mark.parametrize("number", [OWNER_NUMBER, ACCOUNT_NUMBER])
def test_own_and_owner_numbers_are_no_recipient_and_cannot_be_sent_to(world: World, number: str) -> None:
    assert _composer(world, number)["state"] == "no_recipient"
    response = _post(world, uuid4(), key=number)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert _rows(world) == []
    world.enqueue.assert_not_called()


@pytest.mark.parametrize(
    ("change", "state", "key"),
    [
        ({"outbound_mode": OutboundMode.draft}, "draft_mode", TINA),
        ({"paused": True}, "paused", TINA),
        ({}, "window_closed", BOB),
    ],
)
def test_a_new_message_is_refused_while_the_composer_is_closed(
    world: World, change: dict[str, Any], state: str, key: str
) -> None:
    _set_company(world, **change)
    response = _post(world, uuid4(), key=key)
    assert (response.status_code, response.json()) == (409, {"detail": f"cannot send: {state}"})
    assert _rows(world) == []
    world.enqueue.assert_not_called()


def test_a_replay_while_the_composer_is_closed_returns_the_row_and_re_enqueues(world: World) -> None:
    cmid = uuid4()
    first = _post(world, cmid)
    _set_company(world, outbound_mode=OutboundMode.draft)
    again = _post(world, cmid)
    assert (again.status_code, again.json()["id"]) == (202, first.json()["id"])
    assert world.enqueue.call_count == 2
    assert len(_rows(world, cmid)) == 1


def test_draft_mode_wins_over_window_closed(world: World) -> None:
    _set_company(world, outbound_mode=OutboundMode.draft)
    assert _composer(world, BOB)["state"] == "draft_mode"


def test_a_chat_with_no_person_or_identity_can_be_sent_to(world: World) -> None:
    thread = world.client.get(f"/api/chats/{TINA}/messages").json()
    assert (thread["name"], thread["person_kind"]) == (None, None)  # nobody in the directory knows this number
    assert _post(world, uuid4()).status_code == 202


def test_the_inbox_section_guards_send_and_suggestions(world: World, pg_url: str) -> None:
    clerk = add_person_to_team(world.engine, world.cid, "clerk@a.test", role="member", sections=["contacts"])
    settings = make_settings(pg_url)
    with TestClient(world.client.app) as other:
        other.cookies.set(COOKIE, issue_session(settings, clerk, datetime.now(UTC)))
        body = {"client_msg_id": str(uuid4()), "text": "x"}
        assert other.post(f"/api/chats/{TINA}/messages", json=body, headers=CSRF).status_code == 403
        assert other.get(f"/api/chats/{TINA}/suggestions").status_code == 403
    world.enqueue.assert_not_called()
    assert _rows(world) == []


def test_a_reply_in_a_chat_only_chat_stays_out_of_the_pipeline_world(world: World) -> None:
    """Tina is no directory contact: her chat is Chats-only, so his reply to her is too. A known contact's is not."""
    with Session(world.engine) as s, s.begin():
        person = Person(company_id=world.cid, kind=PersonKind.tenant, display_name="Carl", valid_from=date(2026, 1, 1))
        s.add(person)
        s.flush()
        s.add(
            ChannelIdentity(
                company_id=world.cid,
                person_id=person.id,
                channel=Channel.whatsapp,
                identity=CARL,
                valid_from=date(2026, 1, 1),
            )
        )
    tina, carl = uuid4(), uuid4()
    assert _post(world, tina).status_code == 202
    assert _post(world, carl, key=CARL).status_code == 202
    assert [r.pipeline_status for r in _rows(world, tina)] == [PipelineStatus.skipped]
    assert [r.pipeline_status for r in _rows(world, carl)] == [PipelineStatus.done]

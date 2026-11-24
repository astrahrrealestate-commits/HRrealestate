"""Owner-chat guards that sit around the happy path: the allowlist dispatch, the client id index, the stuck sweep."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import sleep
from typing import Any
from uuid import uuid4

import pytest
from dbos import DBOS
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import FakeWhatsAppOutbound
from app.contracts import Channel, Direction, OutboundMode
from app.core.settings import Settings
from app.db.enums import DeliveryStatus, SendStatus
from app.db.models import Company, MessageRow, Send
from app.db.models.ingestion import CLIENT_MSG_ID_INDEX
from app.sender import stuck
from app.sender.delivery import STUCK, STUCK_AFTER
from app.sender.errors import SendBlockedError
from app.sender.owner_chat import assert_chat, chat_plan, send_chat_message
from app.sender.plan import Plan
from app.sender.targets import assert_allowed
from app.workflows import sweeps as sweeps_wf
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch
from tests.integration.chat_send_support import TEXT, Pending, pending_row, row_of, send_of
from tests.integration.conftest import purge_company
from tests.integration.send_mode_support import TENANT_NR, Env, make_env, prior_send, set_company

pytestmark = pytest.mark.integration


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


def plan_of(env: Env, p: Pending) -> Plan:
    return chat_plan(row_of(env, p.id))


def assert_chat_refuses(env: Env, plan: Plan, reason: str | None = None) -> None:
    with Session(env.engine) as s, pytest.raises(SendBlockedError) as caught:
        assert_chat(s, env.company_id, plan)
    assert reason is None or reason in str(caught.value)


def test_assert_allowed_hands_a_chat_plan_to_assert_chat(env: Env) -> None:
    p = pending_row(env)
    plan = plan_of(env, p)
    with Session(env.engine) as s:
        assert_allowed(s, env.company_id, plan)  # a valid chat plan passes (no other branch would let it through)
    set_company(env, outbound_mode=OutboundMode.draft)
    with Session(env.engine) as s, pytest.raises(SendBlockedError, match="switched off"):
        assert_allowed(s, env.company_id, plan)  # the refusal is assert_chat's, not the generic allowlist's


def test_assert_chat_refuses_a_missing_row(env: Env) -> None:
    plan = replace(plan_of(env, pending_row(env)), chat_message_id=uuid4())
    assert_chat_refuses(env, plan, "message not found")


def test_assert_chat_refuses_a_row_without_a_client_id(env: Env) -> None:
    p = pending_row(env)
    plan = plan_of(env, p)
    with Session(env.engine) as s, s.begin():
        row = s.get_one(MessageRow, p.id)
        row.meta = {}
    assert_chat_refuses(env, plan, "message not found")


def test_assert_chat_refuses_a_plan_that_differs_from_the_stored_row(env: Env) -> None:
    plan = plan_of(env, pending_row(env))
    other = "+31600000555"
    assert_chat_refuses(env, replace(plan, target=other, whatsapp=payloads.text(other, TEXT)), "does not match")
    assert_chat_refuses(env, replace(plan, whatsapp=payloads.text(TENANT_NR, "Een ander bericht")), "does not match")
    assert_chat_refuses(env, replace(plan, whatsapp=payloads.text(other, TEXT)), "does not match")


def test_assert_chat_refuses_another_companys_row(env: Env, migrated_engine: Engine) -> None:
    plan = plan_of(env, pending_row(env))
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    try:
        with Session(migrated_engine) as s, pytest.raises(SendBlockedError):
            assert_chat(s, other.id, plan)
    finally:
        purge_company(migrated_engine, other.id)


def test_the_database_refuses_two_outbound_rows_with_one_client_msg_id(env: Env) -> None:
    first = pending_row(env)
    with pytest.raises(IntegrityError):
        pending_row(env, client_msg_id=first.client_msg_id)


def test_the_client_id_index_only_covers_outbound_whatsapp_rows(env: Env) -> None:
    first = pending_row(env)
    with Session(env.engine) as s, s.begin():
        s.add(
            MessageRow(
                company_id=env.company_id,
                raw_event_id=s.get_one(MessageRow, first.id).raw_event_id,
                channel=Channel.gmail,
                provider_msg_id=f"g-{uuid4()}",
                thread_ref="t",
                sender_identity="a@b.test",
                direction=Direction.outbound,
                sent_at=datetime.now(UTC),
                text="x",
                meta={"client_msg_id": str(first.client_msg_id)},
            )
        )  # same id on another channel: allowed


@pytest.fixture
def no_client_id_index(env: Env) -> Iterator[None]:
    """Simulates a database without the unique index, to prove the sender does not rely on it alone."""
    index = next(i for i in MessageRow.__table__.indexes if i.name == CLIENT_MSG_ID_INDEX)
    index.drop(env.engine)
    yield
    with Session(env.engine) as s, s.begin():
        s.execute(
            delete(MessageRow).where(
                MessageRow.company_id == env.company_id, MessageRow.direction == Direction.outbound
            )
        )
    index.create(env.engine)


@pytest.mark.usefixtures("no_client_id_index")
def test_two_rows_same_client_msg_id_second_is_not_marked_sent(env: Env) -> None:
    first = pending_row(env)
    assert send_chat_message(env.deps, env.company_id, first.id).status == "sent"
    second = pending_row(env, client_msg_id=first.client_msg_id)  # only possible without the unique index
    outcome = send_chat_message(env.deps, env.company_id, second.id)
    assert (outcome.status, outcome.reason) == ("blocked", "duplicate client message id")
    row = row_of(env, second.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"] == "duplicate client message id"
    assert len(env.wa.sent) == 1  # never a second provider call for the same client id


def old(env: Env, p: Pending, minutes: float) -> None:
    prior_send(
        env, TENANT_NR, status=SendStatus.sending, key=p.key(env),
        attempted_at=datetime.now(UTC) - timedelta(minutes=minutes),
    )  # fmt: skip


def test_the_sweep_settles_a_stuck_chat_send_and_its_message_row(env: Env) -> None:
    p = pending_row(env)
    old(env, p, STUCK_AFTER.total_seconds() / 60 + 1)
    now = datetime.now(UTC)
    found = stuck.stuck_chats(env.engine, now)
    assert [(c.company_id, c.key) for c in found] == [(env.company_id, p.key(env))]
    assert stuck.settle_chat(env.engine, found[0], now) is True
    send = send_of(env, p.key(env))
    assert send is not None
    assert (send.status, send.error) == (SendStatus.failed, STUCK)
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert str(row.meta["send_error"]).startswith("delivery status unknown")
    assert stuck.settle_chat(env.engine, found[0], now) is False  # once only
    assert stuck.stuck_chats(env.engine, now) == []
    assert env.wa.sent == []


def test_the_sweep_leaves_a_fresh_chat_send_to_its_holder(env: Env) -> None:
    p = pending_row(env)
    old(env, p, 5)
    assert stuck.stuck_chats(env.engine, datetime.now(UTC)) == []
    assert row_of(env, p.id).delivery_status is None


def test_the_sweep_never_settles_another_companys_chat_send(env: Env, migrated_engine: Engine) -> None:
    p = pending_row(env)
    old(env, p, 45)
    item = stuck.StuckChat(uuid4(), p.key(env))  # a key of this company named under a foreign company id
    assert stuck.settle_chat(migrated_engine, item, datetime.now(UTC)) is False
    assert row_of(env, p.id).delivery_status is None


@pytest.fixture
def dbos_env(test_settings: Settings, env: Env) -> Iterator[Env]:
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(env.engine)
    set_sender_deps(env.deps)
    yield env
    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


def test_the_stranded_sweep_workflow_settles_stuck_chat_sends(dbos_env: Env) -> None:
    env = dbos_env
    p = pending_row(env)
    old(env, p, 45)
    sweeps_wf.sweep_stranded(datetime.now(UTC), None)
    assert row_of(env, p.id).delivery_status is DeliveryStatus.failed
    assert env.wa.sent == []


@dataclass
class SlowWhatsApp(FakeWhatsAppOutbound):
    def send(self, payload: dict[str, Any]) -> str:
        sleep(0.6)  # long enough for the second thread to arrive while the first is inside the provider call
        return super().send(payload)


def test_two_workers_delivering_the_same_message_make_one_provider_call(env: Env) -> None:
    wa = SlowWhatsApp()
    deps = replace(env.deps, whatsapp=wa)
    p = pending_row(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send_chat_message, deps, env.company_id, p.id) for _ in range(2)]
        statuses = sorted(f.result().status for f in futures)
    assert len(wa.sent) == 1
    assert statuses in (["already", "sent"], ["in_progress", "sent"])
    assert row_of(env, p.id).delivery_status is DeliveryStatus.sent
    with Session(env.engine) as s:
        assert len(list(s.scalars(select(Send.id).where(Send.company_id == env.company_id)))) == 1

"""Owner-typed WhatsApp sends (ADR 0013): the sender trusts only the stored outbound row, never a passed-in number."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import WhatsAppSendError
from app.contracts import Channel, Direction, OutboundMode
from app.core.ids import new_id
from app.core.workflow_names import chat_workflow_id
from app.db.enums import DeliveryStatus, SendStatus
from app.db.models import ChannelAccount, Company, MessageRow, Send
from app.sender.delivery import STUCK_AFTER, SenderDeps
from app.sender.owner_chat import send_chat_message
from app.sender.tenant_gate import tenant_sends_last_hour
from tests.integration.chat_send_support import TEXT, Pending, add_inbound, all_sends, pending_row, row_of, send_of
from tests.integration.conftest import purge_company
from tests.integration.send_mode_support import OWNER, TENANT_NR, Env, make_env, prior_send, set_company

pytestmark = pytest.mark.integration


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


def assert_refused(env: Env, p: Pending, reason: str) -> None:
    outcome = send_chat_message(env.deps, env.company_id, p.id)
    assert (outcome.status, outcome.reason) == ("blocked", reason)
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"] == reason
    assert TEXT not in row.meta["send_error"]
    assert env.wa.sent == []
    assert send_of(env, p.key(env)) is None


class RaisingWhatsApp:
    def __init__(self, error: WhatsAppSendError) -> None:
        self.error, self.calls = error, 0

    def send(self, payload: dict[str, Any]) -> str:
        self.calls += 1
        raise self.error


def with_wa(env: Env, wa: Any) -> SenderDeps:
    return replace(env.deps, whatsapp=wa)


def test_sends_once_and_marks_row_sent_with_wamid(env: Env) -> None:
    p = pending_row(env)
    outcome = send_chat_message(env.deps, env.company_id, p.id)
    assert outcome.status == "sent"
    assert len(env.wa.sent) == 1
    wamid = env.wa.sent[0].wamid
    assert outcome.provider_ref == wamid
    row = row_of(env, p.id)
    assert (row.provider_msg_id, row.delivery_status) == (wamid, DeliveryStatus.sent)
    send = send_of(env, p.key(env))
    assert send is not None
    assert (send.status, send.target, send.channel, send.provider_ref) == (
        SendStatus.sent, TENANT_NR, Channel.whatsapp, wamid,
    )  # fmt: skip
    assert env.wa.sent[0].payload["text"]["body"] == TEXT


def test_replay_same_message_sends_once(env: Env) -> None:
    p = pending_row(env)
    first = send_chat_message(env.deps, env.company_id, p.id)
    second = send_chat_message(env.deps, env.company_id, p.id)
    assert (first.status, second.status) == ("sent", "already")
    assert second.provider_ref == first.provider_ref
    assert len(env.wa.sent) == 1
    assert all_sends(env) == 1


def test_replay_after_send_finished_but_row_not_updated_finishes_the_row(env: Env) -> None:
    p = pending_row(env)
    prior_send(env, TENANT_NR, key=p.key(env))
    with Session(env.engine) as s, s.begin():
        s.execute(update(Send).where(Send.idempotency_key == p.key(env)).values(provider_ref="wamid.EARLIER"))
    outcome = send_chat_message(env.deps, env.company_id, p.id)
    assert (outcome.status, outcome.provider_ref) == ("already", "wamid.EARLIER")
    assert env.wa.sent == []
    row = row_of(env, p.id)
    assert (row.provider_msg_id, row.delivery_status) == ("wamid.EARLIER", DeliveryStatus.sent)


def test_recipient_is_thread_ref_never_payload(env: Env) -> None:
    p = pending_row(env, recipient="+31699999999", to="+31688888888", phone="+31677777777")
    assert send_chat_message(env.deps, env.company_id, p.id).status == "sent"
    assert [s.payload["to"] for s in env.wa.sent] == ["31612345678"]


def test_unknown_number_inside_window_can_be_answered(env: Env) -> None:
    add_inbound(env, "+31698765432")
    p = pending_row(env, thread="+31698765432")
    assert send_chat_message(env.deps, env.company_id, p.id).status == "sent"
    assert [s.payload["to"] for s in env.wa.sent] == ["31698765432"]


def test_roommate_number_without_inbound_refused(env: Env) -> None:
    assert_refused(env, pending_row(env, thread="+31655555555"), "no inbound message from this number")


def test_company_a_cannot_send_to_company_b_number(env: Env, migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    try:
        add_inbound(env, "+31677777777", company_id=other.id)
        assert_refused(env, pending_row(env, thread="+31677777777"), "no inbound message from this number")
    finally:
        purge_company(migrated_engine, other.id)


def test_message_of_another_company_is_not_found(env: Env, migrated_engine: Engine) -> None:
    p = pending_row(env)
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    try:
        outcome = send_chat_message(env.deps, other.id, p.id)
        assert (outcome.status, outcome.reason) == ("blocked", "message not found")
        assert row_of(env, p.id).delivery_status is None
        assert env.wa.sent == []
    finally:
        purge_company(migrated_engine, other.id)


def test_owner_number_is_refused(env: Env) -> None:
    add_inbound(env, OWNER)  # the owner writing from his own phone is an inbound row too
    assert_refused(env, pending_row(env, thread=OWNER), "this number belongs to the company")


def test_company_whatsapp_account_number_is_refused(env: Env) -> None:
    account = "+31600000200"
    with Session(env.engine) as s, s.begin():
        s.add(ChannelAccount(company_id=env.company_id, channel=Channel.whatsapp, address=account))
    add_inbound(env, account)  # an echo of the company's own line is an inbound row too
    assert_refused(env, pending_row(env, thread=account), "this number belongs to the company")


@pytest.mark.parametrize("thread", ["0612345678", "abc"])
def test_non_e164_thread_ref_is_refused_as_no_inbound(env: Env, thread: str) -> None:
    add_inbound(env, thread)
    assert_refused(env, pending_row(env, thread=thread), "no inbound message from this number")


def test_paused_company_is_refused(env: Env) -> None:
    set_company(env, paused=True)
    assert_refused(env, pending_row(env), "company paused")


def test_draft_mode_is_refused(env: Env) -> None:
    set_company(env, outbound_mode=OutboundMode.draft)
    assert_refused(env, pending_row(env), "sending is switched off for this company")


def test_window_closed_is_refused(env: Env) -> None:
    old = datetime.now(UTC) - timedelta(hours=24)
    with Session(env.engine) as s, s.begin():
        s.execute(
            update(MessageRow)
            .where(MessageRow.company_id == env.company_id, MessageRow.direction == Direction.inbound)
            .values(sent_at=old, created_at=old)
        )
    reason = "WhatsApp window closed: the contact wrote more than 23 h ago"
    assert_refused(env, pending_row(env), reason)


def test_empty_and_too_long_text_are_refused(env: Env) -> None:
    assert_refused(env, pending_row(env, text="   "), "message is empty")
    long = pending_row(env, text="x" * (payloads.TEXT_BODY_MAX + 1))
    outcome = send_chat_message(env.deps, env.company_id, long.id)
    assert (outcome.status, outcome.reason) == ("blocked", "message is too long")
    assert env.wa.sent == []


def test_text_at_the_limit_is_sent_untrimmed(env: Env) -> None:
    body = "y" * payloads.TEXT_BODY_MAX
    assert send_chat_message(env.deps, env.company_id, pending_row(env, text=body).id).status == "sent"
    assert env.wa.sent[0].payload["text"]["body"] == body


def test_ambiguous_failure_marks_failed_and_is_not_retried(env: Env) -> None:
    err = WhatsAppSendError("timeout", code=None, http_status=None, retryable=False, maybe_sent=True)
    wa = RaisingWhatsApp(err)
    deps, p = with_wa(env, wa), pending_row(env)
    first = send_chat_message(deps, env.company_id, p.id)
    assert first.status == "failed"
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"].startswith("may have been delivered")
    assert TEXT not in row.meta["send_error"]
    second = send_chat_message(deps, env.company_id, p.id)
    assert second.status == "failed"
    assert wa.calls == 1


def test_definitely_not_sent_error_is_retryable(env: Env) -> None:
    err = WhatsAppSendError("connect failed", code=None, http_status=None, retryable=True, maybe_sent=False)
    p = pending_row(env)
    with pytest.raises(WhatsAppSendError):
        send_chat_message(with_wa(env, RaisingWhatsApp(err)), env.company_id, p.id)
    send = send_of(env, p.key(env))
    assert send is not None
    assert send.status is SendStatus.pending
    assert row_of(env, p.id).delivery_status is None
    assert send_chat_message(env.deps, env.company_id, p.id).status == "sent"  # the step retry delivers once
    assert len(env.wa.sent) == 1


def test_owner_chat_cap_refuses_at_the_cap_and_passes_below_it(env: Env) -> None:
    deps = replace(env.deps, owner_chat_sends_per_hour=2)
    prior_send(env, TENANT_NR, key=chat_workflow_id(env.company_id, new_id()))
    assert send_chat_message(deps, env.company_id, pending_row(env).id).status == "sent"  # 1 prior < 2
    outcome = send_chat_message(deps, env.company_id, pending_row(env).id)  # 2 chat sends in the last hour
    assert (outcome.status, outcome.reason) == ("blocked", "hourly send cap reached")
    assert len(env.wa.sent) == 1


def test_owner_chat_cap_is_separate_from_tenant_cap(env: Env) -> None:
    deps = replace(env.deps, owner_chat_sends_per_hour=30)  # counting these 30 tenant sends would refuse this one
    for _ in range(30):
        prior_send(env, "+31611111111")  # AI-drafted tenant replies, as many as the tenant cap allows
    assert send_chat_message(deps, env.company_id, pending_row(env).id).status == "sent"


def test_per_number_cap_19_passes_and_20_refuses(env: Env) -> None:
    for _ in range(19):
        prior_send(env, TENANT_NR, key=chat_workflow_id(env.company_id, new_id()))
    assert send_chat_message(env.deps, env.company_id, pending_row(env).id).status == "sent"  # the 20th message
    again = send_chat_message(env.deps, env.company_id, pending_row(env).id)  # 20 already went to this number
    assert (again.status, again.reason) == ("blocked", "too many messages to this number this hour")
    assert len(env.wa.sent) == 1


def test_per_number_cap_counts_only_that_number(env: Env) -> None:
    for _ in range(20):
        prior_send(env, "+31600000777", key=chat_workflow_id(env.company_id, new_id()))
    assert send_chat_message(env.deps, env.company_id, pending_row(env).id).status == "sent"


def test_chat_sends_do_not_count_against_the_tenant_cap(env: Env) -> None:
    for _ in range(5):
        prior_send(env, TENANT_NR, key=chat_workflow_id(env.company_id, new_id()))
    with Session(env.engine) as s:
        assert tenant_sends_last_hour(s, env.company_id, "exec:x:1", datetime.now(UTC)) == 0


def test_fresh_sending_row_is_left_to_its_holder(env: Env) -> None:
    p = pending_row(env)
    prior_send(env, TENANT_NR, status=SendStatus.sending, key=p.key(env), attempted_at=datetime.now(UTC))
    assert send_chat_message(env.deps, env.company_id, p.id).status == "in_progress"
    assert row_of(env, p.id).delivery_status is None
    assert env.wa.sent == []


def test_old_sending_row_is_left_to_the_sweep_not_settled_by_the_attempt(env: Env) -> None:
    p = pending_row(env)
    old = datetime.now(UTC) - STUCK_AFTER - timedelta(minutes=1)
    prior_send(env, TENANT_NR, status=SendStatus.sending, key=p.key(env), attempted_at=old)
    assert send_chat_message(env.deps, env.company_id, p.id).status == "in_progress"
    assert row_of(env, p.id).delivery_status is None
    assert env.wa.sent == []


def test_only_pending_outbound_whatsapp_rows_are_sent(env: Env) -> None:
    with Session(env.engine) as s:
        inbound_id = s.scalars(
            select(MessageRow.id).where(
                MessageRow.company_id == env.company_id, MessageRow.direction == Direction.inbound
            )
        ).first()
    assert inbound_id is not None
    outcome = send_chat_message(env.deps, env.company_id, inbound_id)
    assert (outcome.status, outcome.reason) == ("blocked", "message not found")
    assert env.wa.sent == []


def test_row_without_client_msg_id_is_not_sent(env: Env) -> None:
    p = pending_row(env)
    with Session(env.engine) as s, s.begin():
        s.execute(update(MessageRow).where(MessageRow.id == p.id).values(meta={}))
    outcome = send_chat_message(env.deps, env.company_id, p.id)
    assert (outcome.status, outcome.reason) == ("blocked", "message has no client id")
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"] == "message has no client id"
    assert env.wa.sent == []

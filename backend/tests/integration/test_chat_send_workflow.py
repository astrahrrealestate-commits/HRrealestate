"""`chat.send_message` on Postgres + DBOS: one provider call per client message, terminal handling, settlement steps."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from dbos import DBOS, DBOSClient, SetWorkflowID, WorkflowHandle
from dbos._error import DBOSMaxStepRetriesExceeded
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.api.v1.enqueue import enqueue_chat_send
from app.channels.whatsapp.outbound import WhatsAppSendError
from app.contracts import ActionType, CaseState, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.core.workflow_names import CHAT_QUEUE
from app.db.enums import ActionStatus, ApprovalStatus, DeliveryStatus, SendStatus, TaskStatus
from app.db.models import ActionRow, Approval, Case, Company, MessageRow, RawEvent, Send, TaskRow
from app.ingestion.repository import status_event_id
from app.pipeline import approvals, chat_repo
from app.sender.owner_chat_settle import NO_CLIENT_ID, fail_exhausted
from app.workflows import chat_send
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch
from tests.integration.chat_send_support import Pending, add_inbound, all_sends, pending_row, row_of, send_of
from tests.integration.conftest import purge_company
from tests.integration.send_mode_support import TENANT_NR, Env, make_env, prior_send, set_company

pytestmark = pytest.mark.integration
FAKE_WAMID = "wamid.FAKE000001"


@pytest.fixture
def env(test_settings: Settings, migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    made = make_env(migrated_engine, committed_company)
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(migrated_engine)
    set_sender_deps(made.deps)
    yield made
    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


class RaisingWhatsApp:
    def __init__(self, error: WhatsAppSendError) -> None:
        self.error, self.calls = error, 0

    def send(self, payload: dict[str, Any]) -> str:
        self.calls += 1
        raise self.error


def _handle(env: Env, p: Pending) -> WorkflowHandle[str]:
    with SetWorkflowID(p.key(env)):
        return DBOS.start_workflow(chat_send.chat_send_wf, str(env.company_id), str(p.id))


def _run(env: Env, p: Pending) -> str:
    return _handle(env, p).get_result()


def _inbound_id(env: Env) -> UUID:
    with Session(env.engine) as s:
        return s.scalars(
            select(MessageRow.id).where(
                MessageRow.company_id == env.company_id,
                MessageRow.channel == Channel.whatsapp,
                MessageRow.direction == Direction.inbound,
            )
        ).first()  # type: ignore[return-value]  # make_env stores one


def _draft(
    env: Env,
    status: ActionStatus = ActionStatus.pending_approval,
    *,
    company_id: UUID | None = None,
    case_id: UUID | None = None,
    context: list[UUID] | None = None,
) -> UUID:
    cid = company_id or env.company_id
    refs = context if context is not None else [_inbound_id(env)]
    with Session(env.engine) as s, s.begin():
        action = ActionRow(
            company_id=cid, case_id=case_id or env.case_id, type=ActionType.reply_draft,
            payload={"kind": "reply_draft", "channel": "whatsapp", "body_variants": ["Optie A", "Optie B"]},
            rationale="r", context_ref=refs, status=status,
        )  # fmt: skip
        s.add(action)
        s.flush()
        approvals.open_approval(s, cid, action.id, 1, urgency=Urgency.normal, now=datetime.now(UTC))
        return action.id


def _action(env: Env, action_id: UUID) -> ActionRow:
    with Session(env.engine) as s:
        return s.scalars(select(ActionRow).where(ActionRow.id == action_id)).one()


def _approval(env: Env, action_id: UUID) -> Approval:
    with Session(env.engine) as s:
        return s.scalars(select(Approval).where(Approval.action_id == action_id)).one()


def test_workflow_sends_and_row_gets_wamid_and_sent(env: Env) -> None:
    p = pending_row(env)
    assert _run(env, p) == "sent"
    row = row_of(env, p.id)
    assert (row.delivery_status, row.provider_msg_id) == (DeliveryStatus.sent, FAKE_WAMID)
    assert len(env.wa.sent) == 1


def test_same_workflow_id_runs_once(env: Env) -> None:
    p = pending_row(env)
    assert (_run(env, p), _run(env, p)) == ("sent", "sent")
    assert len(env.wa.sent) == 1


def test_blocked_send_marks_row_failed_with_reason_and_does_not_retry(env: Env) -> None:
    set_company(env, paused=True)
    p = pending_row(env)
    assert _run(env, p) == "blocked"
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"] == "company paused"
    assert env.wa.sent == []
    assert send_of(env, p.key(env)) is None


def test_status_before_wamid_is_applied(env: Env) -> None:
    with Session(env.engine) as s, s.begin():
        s.add(
            RawEvent(
                company_id=env.company_id,
                provider=Channel.whatsapp,
                provider_msg_id=status_event_id(FAKE_WAMID, DeliveryStatus.delivered),
                payload={},
            )
        )
    p = pending_row(env)
    assert _run(env, p) == "sent"
    assert row_of(env, p.id).delivery_status is DeliveryStatus.delivered


def test_suggestion_action_is_closed_after_send(env: Env) -> None:
    action_id = _draft(env)
    with Session(env.engine) as s:
        assert chat_repo.suggestions(s, env.company_id, TENANT_NR)[0] == action_id
    p = pending_row(env, suggestion_action_id=str(action_id))
    assert _run(env, p) == "sent"
    with Session(env.engine) as s:
        assert chat_repo.suggestions(s, env.company_id, TENANT_NR) == (None, [])
    assert _action(env, action_id).status is ActionStatus.superseded
    assert _approval(env, action_id).status is ApprovalStatus.expired


def test_close_suggestion_leaves_actions_that_moved_on_alone(env: Env) -> None:
    done = _draft(env, ActionStatus.executed)
    p = pending_row(env, suggestion_action_id=str(done))
    assert _run(env, p) == "sent"
    assert _action(env, done).status is ActionStatus.executed
    assert _approval(env, done).status is ApprovalStatus.pending  # untouched: the action was not open


def test_a_failed_send_keeps_its_suggestion_open(env: Env) -> None:
    action_id = _draft(env)
    set_company(env, paused=True)
    p = pending_row(env, suggestion_action_id=str(action_id))
    assert _run(env, p) == "blocked"
    assert _action(env, action_id).status is ActionStatus.pending_approval
    assert _approval(env, action_id).status is ApprovalStatus.pending


def test_a_retryable_failure_is_retried_and_delivers_once(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dbos._outcome.time", SimpleNamespace(sleep=lambda _s: None))
    err = WhatsAppSendError("connect failed", code=None, http_status=None, retryable=True, maybe_sent=False)
    failing = RaisingWhatsApp(err)
    set_sender_deps(replace(env.deps, whatsapp=failing))
    p = pending_row(env)
    with pytest.raises(DBOSMaxStepRetriesExceeded):
        _run(env, p)
    assert failing.calls == chat_send.SEND_RETRY["max_attempts"]  # the whole budget, never more
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed  # terminal handler: nothing else would ever settle it
    assert row.meta["send_error"] == chat_send.GAVE_UP
    assert "connect failed" not in row.meta["send_error"]
    send = send_of(env, p.key(env))
    assert send is not None
    assert send.status is SendStatus.pending


def test_ambiguous_failure_is_not_retried(env: Env) -> None:
    err = WhatsAppSendError("timeout", code=None, http_status=None, retryable=True, maybe_sent=True)
    failing = RaisingWhatsApp(err)
    set_sender_deps(replace(env.deps, whatsapp=failing))
    p = pending_row(env)
    assert _run(env, p) == "failed"
    assert failing.calls == 1
    row = row_of(env, p.id)
    assert row.delivery_status is DeliveryStatus.failed
    assert row.meta["send_error"].startswith("may have been delivered")


def test_in_progress_ends_the_run_and_changes_nothing(env: Env) -> None:
    action_id = _draft(env)
    p = pending_row(env, suggestion_action_id=str(action_id))
    prior_send(env, TENANT_NR, status=SendStatus.sending, key=p.key(env), attempted_at=datetime.now(UTC))
    assert _run(env, p) == "in_progress"
    assert env.wa.sent == []
    assert row_of(env, p.id).delivery_status is None
    assert _action(env, action_id).status is ActionStatus.pending_approval  # not closed: nothing was sent


def _sent_send(env: Env, p: Pending, ref: str) -> None:
    with Session(env.engine) as s, s.begin():
        s.add(
            Send(
                company_id=env.company_id, idempotency_key=p.key(env), channel=Channel.whatsapp, target=TENANT_NR,
                status=SendStatus.sent, provider_ref=ref,
            )
        )  # fmt: skip


def test_terminal_handler_never_overwrites_a_settled_row_or_another_companys(env: Env) -> None:
    settled = pending_row(env)
    assert _run(env, settled) == "sent"
    assert fail_exhausted(env.engine, env.company_id, settled.id, "gave up") is False
    assert row_of(env, settled.id).delivery_status is DeliveryStatus.sent
    held = pending_row(env)
    assert fail_exhausted(env.engine, UUID(int=1), held.id, "gave up") is False  # another company's id: untouched
    assert row_of(env, held.id).delivery_status is None


def test_terminal_handler_settles_a_sent_send_as_sent_with_its_wamid(env: Env) -> None:
    p = pending_row(env)  # the provider took it and the send was recorded, but the row was never settled
    _sent_send(env, p, "wamid.PRIOR1")
    assert fail_exhausted(env.engine, env.company_id, p.id, "gave up") is True
    row = row_of(env, p.id)
    assert (row.delivery_status, row.provider_msg_id) == (DeliveryStatus.sent, "wamid.PRIOR1")
    assert "send_error" not in row.meta


def test_terminal_handler_leaves_a_send_held_by_a_live_attempt_alone(env: Env) -> None:
    p = pending_row(env)
    prior_send(env, TENANT_NR, status=SendStatus.sending, key=p.key(env), attempted_at=datetime.now(UTC))
    assert fail_exhausted(env.engine, env.company_id, p.id, "gave up") is False
    assert row_of(env, p.id).delivery_status is None


def test_terminal_handler_without_a_valid_client_id_marks_failed_not_a_none_key(env: Env) -> None:
    p = pending_row(env)
    with Session(env.engine) as s, s.begin():
        s.execute(update(MessageRow).where(MessageRow.id == p.id).values(meta={"type": "text"}))
    assert fail_exhausted(env.engine, env.company_id, p.id, "gave up") is True
    row = row_of(env, p.id)
    assert (row.delivery_status, row.meta["send_error"]) == (DeliveryStatus.failed, NO_CLIENT_ID)
    assert all_sends(env) == 0


def test_already_branch_settles_the_row_replays_the_receipt_and_closes_the_suggestion(env: Env) -> None:
    action_id = _draft(env)
    p = pending_row(env, suggestion_action_id=str(action_id))
    _sent_send(env, p, "wamid.PRIOR1")  # an earlier run died after the send was recorded
    with Session(env.engine) as s, s.begin():
        s.add(
            RawEvent(
                company_id=env.company_id,
                provider=Channel.whatsapp,
                provider_msg_id=status_event_id("wamid.PRIOR1", DeliveryStatus.delivered),
                payload={},
            )
        )
    assert _run(env, p) == "already"
    row = row_of(env, p.id)
    assert (row.delivery_status, row.provider_msg_id) == (DeliveryStatus.delivered, "wamid.PRIOR1")
    assert env.wa.sent == []
    assert _action(env, action_id).status is ActionStatus.superseded


def test_closing_a_suggestion_closes_the_actions_open_tasks(env: Env) -> None:
    action_id = _draft(env)  # opening the approval creates the owner's open task for it
    with Session(env.engine) as s:
        assert s.scalars(select(TaskRow.status).where(TaskRow.action_id == action_id)).all() == [TaskStatus.open]
    assert _run(env, pending_row(env, suggestion_action_id=str(action_id))) == "sent"
    with Session(env.engine) as s:
        assert s.scalars(select(TaskRow.status).where(TaskRow.action_id == action_id)).all() == [TaskStatus.done]


def test_a_suggestion_of_another_company_is_left_alone(env: Env, migrated_engine: Engine) -> None:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.flush()
        case = Case(company_id=other.id, category=Category.administration, urgency=Urgency.normal, state=CaseState.open)
        s.add(case)
        s.commit()
    try:
        foreign = _draft(env, company_id=other.id, case_id=case.id)
        assert _run(env, pending_row(env, suggestion_action_id=str(foreign))) == "sent"
        assert _action(env, foreign).status is ActionStatus.pending_approval
        assert _approval(env, foreign).status is ApprovalStatus.pending
    finally:
        purge_company(migrated_engine, other.id)


def test_a_suggestion_of_another_chat_or_without_context_is_left_alone(env: Env) -> None:
    add_inbound(env, "+31688888888")
    with Session(env.engine) as s:
        elsewhere = s.scalars(
            select(MessageRow.id).where(
                MessageRow.company_id == env.company_id, MessageRow.sender_identity == "+31688888888"
            )
        ).one()
    other_chat, no_context = _draft(env, context=[elsewhere]), _draft(env, context=[])
    for action_id in (other_chat, no_context):
        assert _run(env, pending_row(env, suggestion_action_id=str(action_id))) == "sent"
        assert _action(env, action_id).status is ActionStatus.pending_approval
        assert _approval(env, action_id).status is ApprovalStatus.pending


def test_only_retry_exhaustion_is_handled_other_errors_propagate_untouched(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise ValueError("bug")

    monkeypatch.setattr("app.workflows.chat_send.send_chat_message", boom)
    p = pending_row(env)
    with pytest.raises(ValueError):
        _run(env, p)
    assert row_of(env, p.id).delivery_status is None  # not our exhaustion: the stuck sweep and the owner see it


def test_api_enqueue_runs_the_send_on_the_chat_queue(env: Env, test_settings: Settings) -> None:
    p = pending_row(env)
    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    try:
        enqueue_chat_send(client, env.company_id, p.client_msg_id, p.id)
        enqueue_chat_send(client, env.company_id, p.client_msg_id, p.id)  # same id: deduped by DBOS
        handle: WorkflowHandle[str] = client.retrieve_workflow(p.key(env))
        assert handle.get_result(polling_interval_sec=0.1) == "sent"
        assert handle.get_status().queue_name == CHAT_QUEUE
    finally:
        client.destroy()
    assert len(env.wa.sent) == 1
    assert row_of(env, p.id).delivery_status is DeliveryStatus.sent

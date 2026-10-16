"""Stuck tenant sends: a worker died mid provider call, DBOS recovered the run, and the sweep settles the row once."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from dbos import DBOS
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Channel, InteractiveChannel
from app.core.settings import Settings
from app.db.enums import ActionStatus, SendStatus
from app.db.models import ActionRow, Company, OwnerAccount, Send
from app.sender import stuck
from app.sender.delivery import STUCK, give_up_stuck
from app.workflows import actions
from app.workflows import sweeps as sweeps_wf
from app.workflows.deps import set_engine, set_sender_deps
from app.workflows.runtime import launch
from tests.integration.send_mode_support import (
    OWNER,
    OWNER_MAIL,
    REPLY,
    TENANT_MAIL,
    TENANT_NR,
    Env,
    alert_count,
    alert_row,
    approved,
    make_env,
    prior_send,
    set_company,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


@pytest.fixture
def dbos_env(test_settings: Settings, env: Env) -> Iterator[Env]:
    """A dashboard owner (alerts are feed rows) and a DBOS executor without crons."""
    with Session(env.engine) as s, s.begin():
        s.execute(
            update(OwnerAccount)
            .where(OwnerAccount.company_id == env.company_id)
            .values(interactive_channel=InteractiveChannel.dashboard)
        )
    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    set_engine(env.engine)
    set_sender_deps(env.deps)
    yield env
    set_sender_deps(None)
    set_engine(None)
    DBOS.destroy()


def _ago(minutes: float | None) -> datetime | None:
    return None if minutes is None else datetime.now(UTC) - timedelta(minutes=minutes)


def _sending(env: Env, minutes: float | None) -> UUID:
    """An approved tenant reply whose attempt claimed the send `minutes` ago and never reported (worker died)."""
    action_id = approved(env, ActionType.reply_draft, REPLY)
    prior_send(env, TENANT_MAIL, status=SendStatus.sending, channel=Channel.gmail, key=f"exec:{action_id}:1",
               action_id=action_id, attempted_at=_ago(minutes))  # fmt: skip
    return action_id


def _state(env: Env, action_id: UUID) -> tuple[ActionStatus | None, SendStatus | None, str | None]:
    with Session(env.engine) as s:
        action = s.scalar(select(ActionRow.status).where(ActionRow.id == action_id))
        send = s.execute(select(Send.status, Send.error).where(Send.action_id == action_id)).first()
    return action, send[0] if send else None, send[1] if send else None


def _mine(env: Env, now: datetime) -> list[stuck.StuckSend]:
    with Session(env.engine) as s:
        return stuck.stuck_for(s, env.company_id, now, stuck.BATCH)


def test_crash_then_recover_settles_the_send_and_action_once_with_one_alert(dbos_env: Env) -> None:
    env = dbos_env
    action_id = _sending(env, 31)
    now = datetime.now(UTC)
    sweeps_wf.sweep_stranded(now, None)
    assert _state(env, action_id) == (ActionStatus.failed, SendStatus.failed, STUCK)
    assert env.replies.replies == []  # nothing is (re)sent
    alert = alert_row(env, action_id)
    assert alert is not None
    assert "may not have reached the tenant" in alert.payload["text"]
    assert "Not sent" not in alert.payload["text"]
    assert alert_count(env) == 1
    sweeps_wf.sweep_stranded(now + timedelta(minutes=5), None)  # the next round: nothing left to settle
    handle = DBOS.start_workflow(actions.execute_action_wf, str(action_id), 1, False)  # a late recovered run
    assert handle.get_result() == "blocked"
    assert _state(env, action_id) == (ActionStatus.failed, SendStatus.failed, STUCK)
    assert alert_count(env) == 1


def test_a_fresh_sending_row_is_in_progress_with_no_alert_and_no_wait(dbos_env: Env) -> None:
    env = dbos_env
    action_id = _sending(env, 5)
    handle = DBOS.start_workflow(actions.execute_action_wf, str(action_id), 1, False)
    assert handle.get_result() == "in_progress"
    names = [step["function_name"] for step in DBOS.list_workflow_steps(handle.get_workflow_id())]
    assert names  # the send step ran
    assert not any("after_execute" in name or "tell_blocked" in name for name in names)
    assert alert_row(env, action_id) is None
    sweeps_wf.sweep_stranded(datetime.now(UTC), None)  # too fresh for the sweep: its holder may still report
    assert _state(env, action_id) == (ActionStatus.approved, SendStatus.sending, None)
    assert alert_count(env) == 0


def test_concurrent_give_ups_have_one_winner_and_one_alert(env: Env) -> None:
    action_id = _sending(env, 40)
    key, now = f"exec:{action_id}:1", datetime.now(UTC)
    assert [give_up_stuck(env.engine, key, now, company_id=env.company_id) for _ in range(2)] == [True, False]
    assert alert_count(env) == 1
    item = stuck.StuckSend(env.company_id, key, action_id, 1)
    assert stuck.settle(env.engine, item, now)  # a retried settle step still tells (keyed): no new row
    assert alert_count(env) == 1


@pytest.mark.parametrize("minutes", [31, None])
def test_old_tenant_sends_still_sending_are_selected_paused_companies_too(env: Env, minutes: float | None) -> None:
    action_id = _sending(env, minutes)
    set_company(env, paused=True)
    assert _mine(env, datetime.now(UTC)) == [stuck.StuckSend(env.company_id, f"exec:{action_id}:1", action_id, 1)]


def test_owner_directed_fresh_and_other_rows_are_never_settled(dbos_env: Env) -> None:
    env, old = dbos_env, 45.0
    fresh = _sending(env, 5)
    owner_actions = []
    for target, channel in ((OWNER, Channel.whatsapp), (OWNER_MAIL.upper(), Channel.gmail)):
        owner_action = approved(env, ActionType.notify_owner, {"kind": "notify_owner", "text": "x"}, ButtonChoice.ok)
        prior_send(env, target, status=SendStatus.sending, channel=channel, key=f"exec:{owner_action}:1",
                   action_id=owner_action, attempted_at=_ago(old))  # fmt: skip
        owner_actions.append(owner_action)
    prior_send(env, TENANT_NR, status=SendStatus.sending, attempted_at=_ago(old))  # not an exec send
    finished = approved(env, ActionType.reply_draft, REPLY)
    prior_send(env, TENANT_MAIL, status=SendStatus.failed, channel=Channel.gmail, key=f"exec:{finished}:1",
               action_id=finished, attempted_at=_ago(old))  # fmt: skip
    now = datetime.now(UTC)
    assert _mine(env, now) == []
    sweeps_wf.sweep_stranded(now, None)
    for action_id in (fresh, *owner_actions):
        assert _state(env, action_id) == (ActionStatus.approved, SendStatus.sending, None)
    assert alert_count(env) == 0


def test_another_companys_view_never_sees_a_stuck_send(env: Env) -> None:
    _sending(env, 31)
    with Session(env.engine) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.flush()
        assert stuck.stuck_for(s, other.id, datetime.now(UTC), stuck.BATCH) == []
        s.rollback()

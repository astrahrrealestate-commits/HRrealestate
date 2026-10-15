"""Commit-then-crash sweep queries: stranded approved actions and pending turns, company-scoped and bounded."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.contracts import ActionType, ButtonChoice, Channel
from app.db.enums import ActionStatus, SendStatus, TurnStatus
from app.db.models import ActionRow, AgentConversation, AgentTurn, Approval, Company, OwnerAccount
from app.pipeline import sweeps
from tests.integration.send_mode_support import REPLY, TENANT_MAIL, Env, approved, make_env, prior_send, set_company

pytestmark = pytest.mark.integration
NOW = datetime.now(UTC)


@pytest.fixture
def env(migrated_engine: Engine, committed_company: Company) -> Env:
    return make_env(migrated_engine, committed_company)


def _decided(env: Env, minutes: float, kind: ActionType = ActionType.reply_draft) -> UUID:
    payload = REPLY if kind is ActionType.reply_draft else {"kind": kind.value, "reason": "x"}
    action_id = approved(env, kind, payload, ButtonChoice.ok)
    with Session(env.engine) as s, s.begin():
        s.execute(
            update(Approval).where(Approval.action_id == action_id).values(decided_at=NOW - timedelta(minutes=minutes))
        )
    return action_id


def _actions(env: Env) -> list[UUID]:
    with Session(env.engine) as s:
        return [row[0] for row in sweeps.stranded_actions(s, env.company_id, NOW, sweeps.BATCH)]


def _turn(env: Env, minutes: float, status: TurnStatus = TurnStatus.pending) -> UUID:
    with Session(env.engine) as s, s.begin():
        owner_id = s.scalar(select(OwnerAccount.id).where(OwnerAccount.company_id == env.company_id))
        assert owner_id is not None
        conversation = AgentConversation(company_id=env.company_id, owner_id=owner_id)
        s.add(conversation)
        s.flush()
        turn = AgentTurn(company_id=env.company_id, conversation_id=conversation.id, text="tasks", status=status,
                         created_at=NOW - timedelta(minutes=minutes))  # fmt: skip
        s.add(turn)
        s.flush()
        return turn.id


def test_approved_actions_without_a_send_row_are_stranded_after_five_minutes(env: Env) -> None:
    stranded = _decided(env, 10)
    escalation = _decided(env, 12, ActionType.escalate)
    fresh = _decided(env, 1)  # the normal enqueue may still be on its way
    stale = _decided(env, 60 * 25)  # beyond the lookback
    sent = _decided(env, 10)
    prior_send(env, TENANT_MAIL, status=SendStatus.pending, channel=Channel.gmail, key=f"exec:{sent}:1",
               action_id=sent)  # fmt: skip
    executed = _decided(env, 10, ActionType.update_case_state)
    with Session(env.engine) as s, s.begin():
        s.execute(update(ActionRow).where(ActionRow.id == executed).values(status=ActionStatus.executed))
    found = _actions(env)
    assert sorted(found) == sorted([stranded, escalation])
    assert {fresh, stale, sent, executed}.isdisjoint(found)


def test_another_companys_view_never_sees_these_rows(env: Env) -> None:
    _decided(env, 10)
    _turn(env, 10)
    with Session(env.engine) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.flush()
        assert sweeps.stranded_actions(s, other.id, NOW, sweeps.BATCH) == []
        assert sweeps.stranded_turns(s, other.id, NOW, sweeps.BATCH) == []
        s.rollback()


def test_pending_turns_older_than_five_minutes_are_stranded(env: Env) -> None:
    stranded = _turn(env, 10)
    fresh, running, done = _turn(env, 1), _turn(env, 10, TurnStatus.running), _turn(env, 10, TurnStatus.done)
    with Session(env.engine) as s:
        found = sweeps.stranded_turns(s, env.company_id, NOW, sweeps.BATCH)
    assert found == [stranded]
    assert {fresh, running, done}.isdisjoint(found)


def test_the_round_is_bounded_and_skips_paused_companies_actions(env: Env) -> None:
    first, second = _decided(env, 10), _decided(env, 11)
    turn = _turn(env, 10)
    actions, turns = sweeps.stranded(env.engine, NOW, limit=1)
    assert len(actions) + len(turns) <= 1
    mine, my_turns = sweeps.stranded(env.engine, NOW)
    assert {first, second} <= {a for a, _, _ in mine}
    assert turn in my_turns
    set_company(env, paused=True)
    paused_actions, paused_turns = sweeps.stranded(env.engine, NOW)
    assert {first, second}.isdisjoint(a for a, _, _ in paused_actions)  # `resume` re-runs them
    assert turn in paused_turns  # a turn still runs: it may be the `resume` command itself

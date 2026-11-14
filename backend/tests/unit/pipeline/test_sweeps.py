"""Commit-then-crash sweep selection (no DB): which enqueues a round makes, under which ids, within which bounds."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from app.contracts import ActionType
from app.pipeline import sweeps
from app.pipeline.sweeps import SweepItem, plan_sweep, window

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
A, B, T = uuid4(), uuid4(), uuid4()


def test_window_is_five_minutes_to_a_day_old() -> None:
    assert window(NOW) == (NOW - timedelta(hours=24), NOW - timedelta(minutes=5))


def test_items_use_the_apis_deterministic_workflow_ids() -> None:
    items = plan_sweep([(A, 2, ActionType.reply_draft), (B, 1, ActionType.create_reminder)], [T], known=())
    assert items == [
        SweepItem("exec", f"exec:{A}:2", (str(A), 2, False)),
        SweepItem("exec", f"exec:{B}:1", (str(B), 1, True)),  # local types run apply_local
        SweepItem("turn", f"concierge:{T}", (str(T),)),
    ]


def test_every_listed_action_type_is_swept() -> None:
    assert set(ActionType) == sweeps.SWEEP_TYPES


def test_ids_dbos_already_knows_are_skipped_and_the_round_is_bounded() -> None:
    actions = [(uuid4(), 1, ActionType.escalate) for _ in range(5)]
    known = {f"exec:{actions[0][0]}:1", f"concierge:{T}"}
    items = plan_sweep(actions, [T], known=known, limit=3)
    assert [i.workflow_id for i in items] == [f"exec:{a}:1" for a, _, _ in actions[1:4]]
    assert plan_sweep(actions, [T], known=(), limit=0) == []


def _sql(stmt: ClauseElement) -> str:
    dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
    return " ".join(str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).split())


def test_action_query_is_company_scoped_bounded_and_needs_no_exec_send() -> None:
    session, company_id = MagicMock(), uuid4()
    session.execute.return_value.all.return_value = []
    assert sweeps.stranded_actions(session, company_id, NOW, 7) == []
    sql = _sql(session.execute.call_args.args[0])
    assert f"actions.company_id = '{company_id}'" in sql
    assert f"sends.company_id = '{company_id}'" in sql
    assert "NOT (EXISTS (SELECT" in sql
    assert "actions.status = 'approved'" in sql
    assert "approvals.decided_at >=" in sql
    assert "approvals.decided_at <" in sql
    assert sql.endswith("LIMIT 7")


def test_turn_query_is_company_scoped_and_pending_only() -> None:
    session, company_id = MagicMock(), uuid4()
    session.scalars.return_value = []
    assert sweeps.stranded_turns(session, company_id, NOW, 5) == []
    sql = _sql(session.scalars.call_args.args[0])
    assert f"agent_turns.company_id = '{company_id}'" in sql
    assert "agent_turns.status = 'pending'" in sql
    assert sql.endswith("LIMIT 5")


def test_round_budget_spans_companies_and_skips_paused_companies_actions() -> None:
    c1, c2, c3 = uuid4(), uuid4(), uuid4()
    session = MagicMock()
    session.execute.return_value.all.return_value = [(c1, True), (c2, False), (c3, False)]
    with (
        patch.object(sweeps, "Session") as session_cls,
        patch.object(sweeps, "stranded_actions", side_effect=lambda s, c, n, lim: [(A, 1, ActionType.escalate)]) as sa,
        patch.object(sweeps, "stranded_turns", side_effect=lambda s, c, n, lim: [T] if lim > 0 else []) as st,
    ):
        session_cls.return_value.__enter__.return_value = session
        actions, turns = sweeps.stranded(MagicMock(), NOW, limit=3)
    assert [call.args[1] for call in sa.call_args_list] == [c2]  # c1 is paused: its actions wait for `resume`
    assert len(actions) + len(turns) == 3
    assert st.call_args_list[0].args[1] == c1  # turns still run in a paused company

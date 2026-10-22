"""Lock order and freshness of the two paths that change a live draft: `supersede.supersede_draft` (owner-requested
redraft) and `approvals.decide` (a decision). Both lock the approval, then the action, each `FOR UPDATE` with the
committed row (`populate_existing`), so neither overwrites what the other committed. A recording session stands in
for Postgres (tests/integration/test_concierge_redraft.py covers the real rows)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.contracts import ButtonChoice, Urgency
from app.db.enums import ActionStatus, ApprovalStatus
from app.pipeline import approvals, supersede

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


class Recorder:
    def __init__(self, *scalars: object) -> None:
        self.sql: list[str] = []
        self.options: list[dict[str, Any]] = []
        self.results = iter(scalars)
        self.session = MagicMock()
        self.session.scalar.side_effect = self.scalar
        self.session.execute.return_value.first.return_value = None  # no earlier revision under the key

    def scalar(self, stmt: Any) -> object:
        dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
        compiled = stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})
        self.sql.append(" ".join(str(compiled).split()))
        self.options.append(dict(stmt.get_execution_options()))
        return next(self.results)


def _rows(status: ActionStatus = ActionStatus.pending_approval) -> tuple[SimpleNamespace, SimpleNamespace]:
    action = SimpleNamespace(id=uuid4(), status=status, draft_version=1)
    approval = SimpleNamespace(id=uuid4(), action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
    return approval, action


def _assert_approval_then_action(rec: Recorder) -> None:
    assert rec.sql[0].startswith("SELECT approvals.")
    assert rec.sql[1].startswith("SELECT actions.")
    for sql, options in zip(rec.sql[:2], rec.options[:2], strict=True):
        assert sql.endswith("FOR UPDATE")
        assert options.get("populate_existing") is True
        assert "company_id = '" in sql


def test_supersede_locks_the_approval_before_the_action() -> None:
    approval, action = _rows()
    rec = Recorder(approval, action)
    locked: object = supersede.lock_live(rec.session, uuid4(), approval.id, now=NOW)
    assert locked == (approval, action)
    _assert_approval_then_action(rec)


def test_only_a_pending_approval_or_a_stale_edit_is_supersedable() -> None:
    rec = Recorder(None)
    assert supersede.lock_live(rec.session, uuid4(), uuid4(), now=NOW) is None  # filtered out: no action lock
    assert len(rec.sql) == 1
    where = rec.sql[0]
    assert "approvals.status = 'pending'" in where
    assert "approvals.status = 'edited' AND approvals.decided_at < '2026-10-21 09:00:00+00:00'" in where  # NOW - 24 h


def test_a_decided_action_or_a_newer_version_is_not_supersedable() -> None:
    approval, action = _rows(ActionStatus.approved)
    assert supersede.lock_live(Recorder(approval, action).session, uuid4(), approval.id, now=NOW) is None
    approval, action = _rows()
    action.draft_version = 2
    assert supersede.lock_live(Recorder(approval, action).session, uuid4(), approval.id, now=NOW) is None


def test_supersede_refused_changes_nothing() -> None:
    rec = Recorder(None)  # the edit tap (or an approve) committed first: the row no longer matches the filter
    revision = supersede.supersede_draft(
        rec.session, uuid4(), uuid4(), ["a", "b"], editor="agent:t:0", urgency=Urgency.normal, now=NOW
    )
    assert revision is None
    rec.session.add.assert_not_called()


def test_decide_locks_approval_then_action_with_fresh_rows() -> None:
    approval, action = _rows()
    rec = Recorder(approval, action)
    decision = approvals.decide(rec.session, uuid4(), approval.id, ButtonChoice.rej, at=NOW)
    assert decision.kind == "rejected"
    _assert_approval_then_action(rec)


def test_decide_on_a_superseded_approval_is_stale_and_mutates_nothing() -> None:
    approval, action = _rows()
    approval.status = ApprovalStatus.expired  # the committed row, read under the lock: a redraft expired it
    rec = Recorder(approval, action)
    decision = approvals.decide(rec.session, uuid4(), approval.id, ButtonChoice.ok, at=NOW)
    assert (decision.kind, decision.draft_version) == ("stale", 1)
    assert len(rec.sql) == 1  # the action is never read, locked or changed
    assert (action.status, approval.status) == (ActionStatus.pending_approval, ApprovalStatus.expired)
    rec.session.flush.assert_not_called()


def test_decide_on_an_approval_whose_action_moved_on_is_stale() -> None:
    approval, action = _rows()
    action.draft_version = 2  # superseded between the gate's read and the lock
    rec = Recorder(approval, action)
    decision = approvals.decide(rec.session, uuid4(), approval.id, ButtonChoice.ok, at=NOW + timedelta(seconds=1))
    assert decision.kind == "stale"
    assert action.status is ActionStatus.pending_approval  # never approved

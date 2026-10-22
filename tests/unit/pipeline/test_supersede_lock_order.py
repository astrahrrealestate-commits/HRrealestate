"""`supersede_draft` locks in the order decide/edit use (approval, then action) and never overwrites a decision that
committed while it waited. A recording session stands in for Postgres (tests/integration/test_concierge_redraft.py
covers the real rows)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.contracts import Urgency
from app.db.enums import ActionStatus, ApprovalStatus
from app.pipeline import approvals

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)


def _session(*scalars: object) -> tuple[MagicMock, list[str]]:
    seen: list[str] = []
    dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
    results = iter(scalars)

    def scalar(stmt: Any) -> object:
        seen.append(" ".join(str(stmt.compile(dialect=dialect)).split()))
        return next(results)

    session = MagicMock()
    session.scalar.side_effect = scalar
    session.execute.return_value.first.return_value = None  # no earlier revision under the key
    return session, seen


def _rows(status: ActionStatus = ActionStatus.pending_approval) -> tuple[SimpleNamespace, SimpleNamespace]:
    action = SimpleNamespace(id=uuid4(), status=status, draft_version=1)
    approval = SimpleNamespace(id=uuid4(), action_id=action.id, draft_version=1, status=ApprovalStatus.pending)
    return approval, action


def test_the_approval_is_locked_before_the_action() -> None:
    approval, action = _rows()
    session, seen = _session(approval, action, ApprovalStatus.pending)
    locked: object = approvals.lock_live(session, uuid4(), approval.id)
    assert locked == (approval, action)
    assert seen[0].startswith("SELECT approvals.")
    assert seen[0].endswith("FOR UPDATE")
    assert seen[1].startswith("SELECT actions.")
    assert seen[1].endswith("FOR UPDATE")
    assert "approvals.status = " in seen[0]  # only a pending approval is taken
    assert all("company_id" in sql for sql in seen)


def test_a_decision_that_committed_while_waiting_is_not_overwritten() -> None:
    approval, action = _rows()
    session, _ = _session(approval, action, ApprovalStatus.edited)  # an edit tap committed in between
    revision = approvals.supersede_draft(
        session, uuid4(), approval.id, ["a", "b"], editor="agent:t:0", urgency=Urgency.normal, now=NOW
    )
    assert revision is None
    assert approval.status is ApprovalStatus.pending  # never marked expired
    session.add.assert_not_called()


def test_a_decided_action_or_a_newer_version_is_not_live() -> None:
    approval, action = _rows(ActionStatus.approved)
    assert approvals.lock_live(_session(approval, action, ApprovalStatus.pending)[0], uuid4(), approval.id) is None
    approval, action = _rows()
    action.draft_version = 2
    assert approvals.lock_live(_session(approval, action, ApprovalStatus.pending)[0], uuid4(), approval.id) is None
    assert approvals.lock_live(_session(None)[0], uuid4(), uuid4()) is None  # no pending approval: no action lock

"""`approved_unexecuted` SQL shape (no DB; the integration suite runs it): held or finished exec sends are skipped."""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from app.pipeline.approvals import approved_unexecuted


def _sql() -> str:
    session = MagicMock()
    session.execute.return_value.all.return_value = []
    company_id = uuid4()
    assert approved_unexecuted(session, company_id) == []
    stmt: ClauseElement = session.execute.call_args.args[0]
    dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
    return str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_actions_with_a_non_pending_exec_send_are_excluded() -> None:
    sql = " ".join(_sql().split())
    assert "NOT (EXISTS (SELECT" in sql
    assert "sends.status != 'pending'" in sql
    assert "'exec:' || CAST(actions.id AS VARCHAR) || ':' || CAST(actions.draft_version AS VARCHAR)" in sql
    assert sql.count("company_id = '") >= 2  # the action and the send are both company-scoped

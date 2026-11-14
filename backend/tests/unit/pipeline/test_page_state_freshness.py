"""Server-side freshness of warmed page facts (Task 4 fix round 1): a newer message, approval (created or decided) or
case event in the company since `resolved_at` makes the turn resolve cold; a failed read never fails the message."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import ANY, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError, ProgrammingError
from structlog.testing import capture_logs

from app.contracts import PageContext
from app.pipeline import page_state as ps

T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
CASE = UUID("01900000-0000-7000-8000-000000000001")
RESOLVED = {"facts": "view: case\nopen case: stored", "dropped": []}
PAGE = PageContext.model_validate({"view": "case", "case_id": str(CASE)})


# ---- the pure predicate -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latest", "fresh"),
    [
        (None, True),  # no messages, approvals or case events at all
        (T0 - timedelta(hours=1), True),
        (T0 - timedelta(seconds=3), True),
        (T0 - ps.FRESHNESS_MARGIN, False),  # inside the margin: a write racing the resolve may be missing
        (T0 - timedelta(seconds=1), False),
        (T0, False),  # equal: counts as changed
        (T0 + timedelta(seconds=1), False),
    ],
)
def test_unchanged_since(latest: datetime | None, fresh: bool) -> None:
    assert ps.unchanged_since(latest, T0) is fresh


def test_the_margin_is_two_seconds() -> None:
    assert timedelta(seconds=2) == ps.FRESHNESS_MARGIN


# ---- the company-scoped check ------------------------------------------------------------------------------------


def test_every_source_is_company_scoped_in_one_statement() -> None:
    company = uuid4()
    stmt = ps.latest_change(company)
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert sql.startswith("SELECT greatest(")
    for part in (
        "SELECT max(messages.created_at) AS max_1 \nFROM messages \nWHERE messages.company_id = ",
        "SELECT max(approvals.created_at) AS max_2 \nFROM approvals \nWHERE approvals.company_id = ",
        "SELECT max(approvals.decided_at) AS max_3 \nFROM approvals \nWHERE approvals.company_id = ",
        "SELECT max(case_events.created_at) AS max_4 \nFROM case_events \nWHERE case_events.company_id = ",
    ):
        assert part in sql, part
    params = stmt.compile().params
    assert len(params) == 4
    assert set(params.values()) == {company}


def _session(row: tuple[Any, ...] | None, latest: datetime | None) -> MagicMock:
    session = MagicMock()
    session.execute.return_value.one_or_none.return_value = row
    session.scalar.return_value = latest
    return session


def _row(age_s: int = 10) -> tuple[Any, ...]:
    return (ps.page_key(PAGE), T0, RESOLVED, T0 + timedelta(seconds=age_s))


@pytest.mark.parametrize("source", ["message", "approval created", "approval decided", "case event"])
def test_any_newer_change_is_a_miss(source: str) -> None:
    """The database computes greatest(...) over the three sources; any one newer than the row gives a newer latest."""
    session = _session(_row(), T0 + timedelta(seconds=5))
    assert ps.warm_resolved(session, uuid4(), uuid4(), PAGE) is None, source


def test_all_older_or_no_rows_is_a_hit() -> None:
    assert ps.warm_resolved(_session(_row(), T0 - timedelta(minutes=5)), uuid4(), uuid4(), PAGE) == RESOLVED
    assert ps.warm_resolved(_session(_row(), None), uuid4(), uuid4(), PAGE) == RESOLVED


def test_the_change_check_runs_only_for_a_candidate_hit() -> None:
    session = _session(_row(age_s=121), None)
    assert ps.warm_resolved(session, uuid4(), uuid4(), PAGE) is None
    session.scalar.assert_not_called()


def test_the_change_check_uses_the_principals_company() -> None:
    session, company = _session(_row(), None), uuid4()
    ps.warm_resolved(session, company, uuid4(), PAGE)
    assert set(session.scalar.call_args.args[0].compile().params.values()) == {company}


# ---- a failed read never fails the message ----------------------------------------------------------------------


def test_a_non_transient_read_failure_gives_the_cold_value_and_logs_the_type_only() -> None:
    session = MagicMock()
    missing = ProgrammingError("select", {}, Exception('relation "agent_page_state" does not exist'))
    with patch.object(ps, "warm_resolved", side_effect=missing), capture_logs() as logs:
        value = ps.turn_page_context(session, CASE, uuid4(), PAGE)
    assert value == PAGE.model_dump(mode="json")
    session.begin_nested.assert_called_once()  # a savepoint: the turn insert still works after the failed read
    failed = [e for e in logs if e["event"] == "dashboard.page_state_read_failed"]
    assert failed == [
        {"event": "dashboard.page_state_read_failed", "company_id": ANY, "error": "ProgrammingError",
         "log_level": "warning"}
    ]  # fmt: skip
    assert "relation" not in str(logs)


def test_a_transient_read_failure_propagates() -> None:
    with (
        patch.object(ps, "warm_resolved", side_effect=OperationalError("select", {}, Exception("down"))),
        pytest.raises(OperationalError),
    ):
        ps.turn_page_context(MagicMock(), CASE, uuid4(), PAGE)


# ---- warm reports whether the row was written --------------------------------------------------------------------


def _warm(returned: Any) -> tuple[bool, MagicMock]:
    session = MagicMock()
    session.execute.return_value.scalar_one_or_none.return_value = returned
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    with (
        patch.object(ps, "Session", factory),
        patch("app.pipeline.concierge_page.resolve_page_facts", return_value=MagicMock(dropped=())),
        patch("app.pipeline.concierge_page.facts_text", return_value="view: case"),
    ):
        return ps.warm(MagicMock(), CASE, uuid4(), PAGE), session


def test_warm_returns_the_written_row() -> None:
    written, session = _warm(uuid4())
    assert written is True
    sql = str(session.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert sql.endswith("RETURNING agent_page_state.id")


def test_warm_reports_a_row_the_guard_kept_as_not_written() -> None:
    written, _ = _warm(None)  # another company's row or a newer resolution: ON CONFLICT ... WHERE kept it
    assert written is False

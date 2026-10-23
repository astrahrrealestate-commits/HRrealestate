"""Stuck tenant sends (no DB): which `sends` rows the 5-minute sweep settles, and how a settle is decided."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from app.db.enums import SendStatus
from app.sender import stuck
from app.sender.delivery import STATUS_UNKNOWN, STUCK, STUCK_AFTER
from app.sender.stuck import StuckSend, candidates, parse_exec_key, stuck_query
from app.sender.tenant_gate import blocked_key

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
A, C = UUID("01900000-0000-7000-8000-00000000000a"), UUID("01900000-0000-7000-8000-00000000000c")  # stable test ids


def _sql(stmt: ClauseElement) -> str:
    dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
    return " ".join(str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).split())


@pytest.mark.parametrize(
    ("key", "parsed"),
    [
        (f"exec:{A}:3", (A, 3)),
        (f"exec:{A}:x", None),
        ("exec:not-a-uuid:1", None),
        (f"exec:{A}:1:resume:r1", None),  # a workflow id, never a send key
        (f"blocked:exec:{A}:1", None),
        (f"approval:{A}:0", None),
    ],
)
def test_parse_exec_key(key: str, parsed: tuple[Any, int] | None) -> None:
    assert parse_exec_key(key) == parsed


def test_candidates_keep_exec_rows_whose_key_names_their_own_action() -> None:
    other = uuid4()
    rows = [(C, f"exec:{A}:2", A), (C, f"exec:{A}:2", other), (C, "exec:bad:1", A), (C, f"exec:{other}:1", None)]
    assert candidates(rows) == [StuckSend(C, f"exec:{A}:2", A, 2)]


def test_the_alert_key_of_a_settled_send_is_the_senders_blocked_key() -> None:
    assert StuckSend(C, f"exec:{A}:2", A, 2).alert_key == blocked_key(A, 2)


def test_query_selects_old_tenant_exec_sends_still_sending_company_scoped_oldest_first() -> None:
    sql = _sql(stuck_query(C, {"+31600000100", "harjot@example.test"}, NOW, 7))
    assert f"sends.company_id = '{C}'" in sql
    assert "sends.status = 'sending'" in sql
    assert "sends.channel IN ('gmail', 'whatsapp')" in sql
    assert "lower(sends.target) NOT IN ('+31600000100', 'harjot@example.test')" in sql
    assert "sends.idempotency_key LIKE 'exec:%" in sql  # the dialect may escape % as %%
    assert "sends.action_id IS NOT NULL" in sql
    assert f"sends.attempted_at <= '{NOW - STUCK_AFTER}" in sql
    assert "sends.attempted_at IS NULL" in sql
    assert "ORDER BY sends.attempted_at ASC NULLS FIRST" in sql
    assert sql.endswith("LIMIT 7")


def test_a_company_without_owners_still_compiles() -> None:
    assert "NOT IN" in _sql(stuck_query(C, set(), NOW, 1))


def test_every_company_is_scanned_paused_too_with_one_shared_budget() -> None:
    first, second, third = uuid4(), uuid4(), uuid4()
    session = MagicMock()
    session.scalars.return_value = [first, second, third]
    found = {first: [StuckSend(first, "k1", A, 1)], second: [StuckSend(second, "k2", A, 1)]}
    calls: list[tuple[Any, int]] = []

    def per_company(_s: Any, company_id: Any, _now: datetime, limit: int) -> list[StuckSend]:
        calls.append((company_id, limit))
        return found.get(company_id, [])

    with patch.object(stuck, "Session") as session_cls, patch.object(stuck, "stuck_for", side_effect=per_company):
        session_cls.return_value.__enter__.return_value = session
        result = stuck.stuck_sends(MagicMock(), NOW, limit=2)
    assert [s.key for s in result] == ["k1", "k2"]
    assert calls == [(first, 2), (second, 1)]  # budget used up: the third company is not queried
    assert "paused" not in _sql(session.scalars.call_args.args[0])  # settling sends nothing: paused too


def _settle(won: bool, row: tuple[SendStatus, str | None] | None) -> tuple[bool, MagicMock]:
    with (
        patch.object(stuck, "give_up_stuck", return_value=won) as give_up,
        patch.object(stuck, "Session") as session_cls,
    ):
        session_cls.return_value.__enter__.return_value.execute.return_value.first.return_value = row
        return stuck.settle(MagicMock(), StuckSend(C, f"exec:{A}:1", A, 1), NOW), give_up


def test_the_winning_settle_reports_settled() -> None:
    settled, give_up = _settle(True, None)
    assert settled
    assert give_up.call_args.args[1:] == (f"exec:{A}:1", NOW)
    assert give_up.call_args.kwargs == {"company_id": C}


def test_a_settle_retried_after_its_commit_still_reports_settled() -> None:
    """The step may die after the commit: the row already failed as stuck, so the (keyed) owner notice still runs."""
    assert _settle(False, (SendStatus.failed, STUCK))[0]


@pytest.mark.parametrize(
    "row", [(SendStatus.sent, None), (SendStatus.failed, STATUS_UNKNOWN), (SendStatus.sending, None), None]
)
def test_a_row_that_finished_otherwise_is_not_settled(row: tuple[SendStatus, str | None] | None) -> None:
    assert not _settle(False, row)[0]

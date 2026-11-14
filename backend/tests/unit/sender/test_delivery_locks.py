"""Delivery transactions (no DB): giving up a stuck send is one conditional update that writes the alert with it,
and every claim path locks the action row before the `sends` row (the order `execute._prepare` uses)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import ClauseElement

from app.contracts import Channel, OwnerMessage
from app.db.enums import FeedKind, SendStatus
from app.sender import delivery
from app.sender.delivery import STUCK, give_up_stuck
from app.sender.plan import Plan
from app.sender.tenant_gate import alert_text, blocked_key

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
A, C = uuid4(), uuid4()
KEY = f"exec:{A}:1"


def _sql(stmt: ClauseElement) -> str:
    dialect: Any = postgresql.dialect()  # type: ignore[no-untyped-call]
    return " ".join(str(stmt.compile(dialect=dialect, compile_kwargs={"literal_binds": True})).split())


def _session(won: tuple[Any, Any] | None, send: Any = None) -> tuple[MagicMock, list[str]]:
    session, seen = MagicMock(), list[str]()

    def scalar(stmt: ClauseElement) -> Any:
        seen.append(_sql(stmt))
        return A

    session.scalar.side_effect = scalar

    def execute(stmt: ClauseElement) -> MagicMock:
        seen.append(_sql(stmt))
        result = MagicMock()
        result.first.return_value = won
        result.scalar_one.return_value = send
        return result

    session.execute.side_effect = execute
    return session, seen


def _give_up(won: tuple[Any, Any] | None, company_id: Any = C) -> tuple[bool, list[str], MagicMock]:
    session, seen = _session(won)
    with (
        patch.object(delivery, "Session") as session_cls,
        patch("app.sender.tenant_gate.feed.deliver") as deliver,
    ):
        session_cls.return_value.__enter__.return_value = session
        return give_up_stuck(MagicMock(), KEY, NOW, company_id=company_id), seen, deliver


def _index(seen: list[str], fragment: str) -> int:
    return next(i for i, sql in enumerate(seen) if fragment in sql)


def test_the_winner_fails_send_and_action_and_writes_the_one_alert_in_the_same_transaction() -> None:
    won, seen, deliver = _give_up((A, C))
    assert won
    assert _index(seen, "FROM actions") < _index(seen, "UPDATE sends")  # action row locked first
    assert "FOR UPDATE" in seen[_index(seen, "FROM actions")]
    update_send = seen[_index(seen, "UPDATE sends")]
    assert "sends.status = 'sending'" in update_send
    assert f"sends.company_id = '{C}'" in update_send
    assert "status='failed'" in update_send
    update_action = seen[_index(seen, "UPDATE actions")]
    assert f"actions.company_id = '{C}'" in update_action
    _, company, key, kind, ref, message = deliver.call_args.args
    assert (company, key, kind, ref) == (C, blocked_key(A, 1), FeedKind.alert, None)
    assert message == OwnerMessage(text=alert_text(STUCK))


def test_a_loser_changes_nothing_and_writes_no_alert() -> None:
    won, seen, deliver = _give_up(None)
    assert not won
    assert not any("UPDATE actions" in sql for sql in seen)
    deliver.assert_not_called()


def test_feed_claimed_locks_the_action_before_the_send() -> None:
    send = SimpleNamespace(status=SendStatus.pending, provider_ref=None, action_id=A, error=None, attempted_at=None)
    session, seen = _session(None, send)
    plan = Plan(Channel.dashboard, "owner:x", company_id=C, owner_message=OwnerMessage(text="x"))
    with (
        patch.object(delivery, "Session") as session_cls,
        patch("app.sender.delivery.feed.deliver", return_value=uuid4()),
    ):
        session_cls.return_value.__enter__.return_value = session
        assert delivery.feed_claimed(MagicMock(), KEY, plan).status == "sent"
    action_lock = _index(seen, "FROM actions")
    send_lock = next(i for i, sql in enumerate(seen) if "FROM sends" in sql and "FOR UPDATE" in sql)
    assert "FOR UPDATE" in seen[action_lock]
    assert f"actions.company_id = '{C}'" in seen[action_lock]
    assert action_lock < send_lock

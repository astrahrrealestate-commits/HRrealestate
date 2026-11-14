"""Unit tests for owner command `remember` (Task C11)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from app.db.models import Company
from app.pipeline.owner_commands import CommandKind, parse_command, run_command


def test_parse_command_remember_variants() -> None:
    cmd1 = parse_command("remember always call Jansen for leaks")
    assert cmd1.kind == CommandKind.remember
    assert cmd1.text == "always call Jansen for leaks"

    cmd2 = parse_command("onthoud cv ketel onderhoud in september")
    assert cmd2.kind == CommandKind.remember
    assert cmd2.text == "cv ketel onderhoud in september"

    cmd3 = parse_command("From now on send polite reminders")
    assert cmd3.kind == CommandKind.remember
    assert cmd3.text == "send polite reminders"


def test_run_command_remember() -> None:
    engine = MagicMock()
    settings = MagicMock()
    company_id = uuid4()
    now = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)

    cmd = parse_command("remember always call Jansen for leaks")

    # Mock Session context manager
    session = MagicMock()
    company = Company(id=company_id)
    session.get.return_value = company
    session.scalar.return_value = None  # no existing memory item

    from unittest.mock import patch

    with patch("app.pipeline.owner_commands.Session") as mock_session_cls:
        mock_session_cls.return_value.__enter__.return_value = session
        reply = run_command(engine, settings, company_id, cmd, now=now)

    assert "Remembered:" in reply
    assert "always call Jansen for leaks" in reply

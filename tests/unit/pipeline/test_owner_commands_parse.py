from datetime import timedelta

import pytest

from app.pipeline.owner_commands import CommandKind, parse_command, parse_duration


@pytest.mark.parametrize(
    ("text", "kind", "index", "duration"),
    [
        ("pause", CommandKind.pause, None, None),
        ("  Resume ", CommandKind.resume, None, None),
        ("tasks", CommandKind.tasks, None, None),
        ("done 2", CommandKind.done, 2, None),
        ("Done 10", CommandKind.done, 10, None),
        ("snooze 1 4h", CommandKind.snooze, 1, timedelta(hours=4)),
        ("snooze 3 2d", CommandKind.snooze, 3, timedelta(days=2)),
        ("waiting", CommandKind.waiting, None, None),
        ("help", CommandKind.help, None, None),
        ("?", CommandKind.help, None, None),
    ],
)
def test_commands(text: str, kind: CommandKind, index: int | None, duration: timedelta | None) -> None:
    cmd = parse_command(text)
    assert (cmd.kind, cmd.index, cmd.duration) == (kind, index, duration)


@pytest.mark.parametrize("text", ["Wat is de status van de lekkage?", "done", "done x", "snooze 1", "snooze 1 9y", ""])
def test_anything_else_is_a_question(text: str) -> None:
    cmd = parse_command(text)
    assert cmd.kind is CommandKind.question
    assert cmd.text == text.strip()


@pytest.mark.parametrize(("raw", "expected"), [("30m", timedelta(minutes=30)), ("1w", timedelta(weeks=1))])
def test_durations(raw: str, expected: timedelta) -> None:
    assert parse_duration(raw) == expected


@pytest.mark.parametrize("raw", ["0h", "9w", "5x", "h"])
def test_bad_durations(raw: str) -> None:
    with pytest.raises(ValueError, match="duration"):
        parse_duration(raw)

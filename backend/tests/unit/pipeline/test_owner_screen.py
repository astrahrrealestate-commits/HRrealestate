import pytest

from app.pipeline.owner_commands import MAX_QUESTION_CHARS, screen_question


@pytest.mark.parametrize("text", ["", "   ", "?!", "🙂🙂", "...."])
def test_blank_or_symbol_only_is_not_a_question(text: str) -> None:
    assert screen_question(text) is not None


def test_too_long_is_rejected() -> None:
    assert screen_question("a" * (MAX_QUESTION_CHARS + 1)) is not None
    assert screen_question("a" * MAX_QUESTION_CHARS) is None


def test_normal_question_passes() -> None:
    assert screen_question("Wat is de status van de lekkage bij Sanne?") is None

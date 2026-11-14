"""Dutch/English detection for tenant messages: cheap, deterministic, no model."""

import pytest

from app.core.language import detect_language


@pytest.mark.parametrize(
    "text",
    [
        "Goedemorgen, de verwarming in mijn appartement werkt niet meer. Kunt u iemand sturen?",
        "Beste meneer Singh, ik heb de huur van deze maand overgemaakt. Groet, Jan",
        "Er is een lekkage in de keuken en het water komt door het plafond.",
        "ok bedankt",
    ],
)
def test_dutch_text_is_nl(text: str) -> None:
    assert detect_language(text) == "nl"


@pytest.mark.parametrize(
    "text",
    [
        "Hello, the heating in my apartment is not working. Could you send someone?",
        "Dear Mr Singh, I have paid this month's rent. Regards, Jan",
        "Thanks, that works for me.",
    ],
)
def test_english_text_is_en(text: str) -> None:
    assert detect_language(text) == "en"


@pytest.mark.parametrize("text", ["", "   ", "12345", "👍", "+31 6 12 34 56 78", "INV-2026-104"])
def test_text_without_words_is_unknown(text: str) -> None:
    assert detect_language(text) == "unknown"


def test_quoted_english_inside_dutch_message_stays_nl() -> None:
    text = "Ik heb een vraag over de huur van het appartement en de borg. The deposit is 1200."
    assert detect_language(text) == "nl"

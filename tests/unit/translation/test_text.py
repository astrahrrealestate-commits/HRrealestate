"""Splitting a message into model-sized sentences and putting the translation back together."""

import pytest

from app.core.errors import TranslationUnavailableError
from app.translation.text import MAX_SEGMENT_CHARS, MAX_SEGMENTS, MAX_TEXT_CHARS, translate_text


class Upper:
    """A fake translator: upper-cases every segment and records what it was asked for."""

    engine = "fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def translate(self, segments: list[str]) -> list[str]:
        self.calls.append(list(segments))
        return [s.upper() for s in segments]


def test_each_sentence_is_translated_on_its_own() -> None:
    tr = Upper()
    out = translate_text(tr, "Kunt u iemand sturen? Het is erg koud.")
    assert tr.calls == [["Kunt u iemand sturen?", "Het is erg koud."]]
    assert out == "KUNT U IEMAND STUREN? HET IS ERG KOUD."


def test_line_breaks_and_blank_lines_survive() -> None:
    out = translate_text(Upper(), "Beste Jan,\n\nBedankt voor je bericht.\nGroet")
    assert out == "BESTE JAN,\n\nBEDANKT VOOR JE BERICHT.\nGROET"


def test_segments_without_letters_are_not_sent_to_the_model() -> None:
    tr = Upper()
    out = translate_text(tr, "Factuur\n+31 6 12 34 56 78\n450,-")
    assert tr.calls == [["Factuur"]]
    assert out == "FACTUUR\n+31 6 12 34 56 78\n450,-"


def test_all_segments_go_to_the_model_in_one_batch() -> None:
    tr = Upper()
    translate_text(tr, "Een. Twee.\nDrie.")
    assert len(tr.calls) == 1


def test_a_sentence_longer_than_the_limit_is_split_at_spaces() -> None:
    tr = Upper()
    translate_text(tr, " ".join(["woord"] * 200))
    assert all(len(s) <= MAX_SEGMENT_CHARS for s in tr.calls[0])
    assert len(tr.calls[0]) > 1


def test_text_beyond_the_cap_is_cut_and_marked() -> None:
    tr = Upper()
    out = translate_text(tr, "Zin. " * 5000)
    assert sum(len(s) for s in tr.calls[0]) <= MAX_TEXT_CHARS
    assert out.endswith("…")


def test_empty_text_needs_no_model() -> None:
    tr = Upper()
    assert translate_text(tr, "  \n ") == ""
    assert tr.calls == []


def test_many_tiny_sentences_are_capped_so_one_request_cannot_flood_the_model() -> None:
    tr = Upper()
    out = translate_text(tr, "a. " * 3000)
    assert len(tr.calls[0]) == MAX_SEGMENTS
    assert out.endswith("…")


def test_dutch_abbreviations_do_not_end_a_sentence() -> None:
    tr = Upper()
    translate_text(tr, "Dhr. Jansen belt morgen. Zie bijv. de factuur, nr. 5 is betaald.")
    assert tr.calls == [["Dhr. Jansen belt morgen.", "Zie bijv. de factuur, nr. 5 is betaald."]]


def test_a_translator_returning_the_wrong_number_of_segments_is_an_error_not_a_garbled_message() -> None:
    class Short(Upper):
        def translate(self, segments: list[str]) -> list[str]:
            return super().translate(segments)[:-1]

    with pytest.raises(TranslationUnavailableError, match="segments"):
        translate_text(Short(), "Een. Twee.")

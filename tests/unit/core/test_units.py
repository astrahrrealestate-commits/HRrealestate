import pytest

from app.core.property_terms import normalise_unit


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("uur", "hour"),
        ("Uren", "hour"),
        ("hour", "hour"),
        ("hours", "hour"),
        ("hr", "hour"),
        ("h", "hour"),
        (" per uur ", "hour"),
        ("/hour", "hour"),
        ("dag", "day"),
        ("dagen", "day"),
        ("day", "day"),
        ("Days", "day"),
        ("stuk", "piece"),
        ("stuks", "piece"),
        ("piece", "piece"),
        ("pcs", "piece"),
        ("st", "piece"),
        ("m", "m"),
        ("meter", "m"),
        ("meters", "m"),
        ("m2", "m2"),
        ("m²", "m2"),
        ("M²", "m2"),
        ("vierkante meter", "m2"),
        ("sqm", "m2"),
        ("square meter", "m2"),
        ("square meters", "m2"),
        ("job", "job"),
        ("klus", "job"),
        ("project", "job"),
        ("lump sum", "job"),
        ("all-in", "job"),
        ("forfait", "job"),
        ("post", "job"),
    ],
)
def test_normalise_unit_maps_dutch_english_and_symbols(text: str, unit: str) -> None:
    assert normalise_unit(text) == unit


def test_normalise_unit_keeps_unknown_text_casefolded_and_stripped() -> None:
    assert normalise_unit("  Liter ") == "liter"
    assert normalise_unit("Kuub") == "kuub"


def test_normalise_unit_is_idempotent() -> None:
    for text in ("uur", "m²", "Lump Sum", "Liter"):
        once = normalise_unit(text)
        assert normalise_unit(once) == once

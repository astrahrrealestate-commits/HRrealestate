import pytest

from app.core.property_terms import ITEM_KEY_MAX, UNIT_MAX, normalise_item_key, normalise_unit


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


def test_item_key_is_bounded_to_the_column_and_cut_on_a_word() -> None:
    compounds = "Badkamerrenovatiewerkzaamheden " * 2 + "Gevelreinigingsonderhoudscontract Dakgootreinigingsabonnement"
    long_token = "x" * 250
    key = normalise_item_key(compounds)

    assert 0 < len(key) <= ITEM_KEY_MAX
    assert not key.endswith("_")
    assert key == normalise_item_key(compounds)  # deterministic: quote lines meet snapshot rows
    assert key.count("_") < 3  # the last word that did not fit was dropped, not cut
    assert normalise_item_key(long_token) == "x" * ITEM_KEY_MAX
    assert normalise_item_key(" ".join(["y" * 50] * 4)) == "_".join(["y" * 50] * 1)
    assert len(normalise_item_key(" ".join(["z" * 40] * 4))) <= ITEM_KEY_MAX


def test_unit_is_bounded_to_the_column() -> None:
    unit = normalise_unit("  Strekkende meter dakgoot inclusief afvoer en hemelwaterafvoer ")

    assert len(unit) <= UNIT_MAX
    assert unit == unit.strip()
    assert unit == normalise_unit(unit)

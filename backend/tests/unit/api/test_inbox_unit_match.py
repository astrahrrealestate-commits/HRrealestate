"""Which of the company's own units a thread names: only a unit label that really appears in the thread counts."""

from app.api.inbox.unit_match import unit_named_in

UNITS = [
    ("Keizersgracht 42-A", "Keizersgracht 42-A, 1015 CS Amsterdam"),
    ("Prinsengracht 118-B", "Prinsengracht 118-B, 1015 EA Amsterdam"),
    ("Lijnbaansgracht 9-C", None),
]


def test_a_unit_label_in_the_text_names_that_unit_with_its_address() -> None:
    text = "Factuur groepenkast Prinsengracht 118-B, graag betalen voor 11 november."
    assert unit_named_in(text, UNITS) == "Prinsengracht 118-B, 1015 EA Amsterdam"


def test_a_unit_without_an_address_shows_its_label() -> None:
    assert unit_named_in("lekkage bij lijnbaansgracht 9-c", UNITS) == "Lijnbaansgracht 9-C"


def test_case_and_spacing_do_not_matter() -> None:
    assert unit_named_in("KEIZERSGRACHT   42-A", UNITS) == "Keizersgracht 42-A, 1015 CS Amsterdam"


def test_two_different_units_name_nothing() -> None:
    assert unit_named_in("Prinsengracht 118-B en Keizersgracht 42-A", UNITS) is None


def test_a_street_alone_or_a_look_alike_number_names_nothing() -> None:
    assert unit_named_in("De Prinsengracht is mooi", UNITS) is None
    assert unit_named_in("Prinsengracht 118-Bis", UNITS) is None


def test_a_sender_name_or_a_common_word_names_nothing() -> None:
    assert unit_named_in("Hoi, de keuken van Emma en Lars", UNITS) is None

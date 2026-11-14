"""M10 linking rules (pure): fuzzy names and addresses, ambiguity, lease validity."""

from datetime import date
from uuid import uuid4

import pytest

from app.pipeline.document_links import active_lease, fold, match_name, match_unit

ANNA, ANNE, JAN, JAN2 = uuid4(), uuid4(), uuid4(), uuid4()
PEOPLE = [(ANNA, "Anna de Vries"), (ANNE, "Anne de Vos"), (JAN, "Jan Bakker"), (JAN2, "Jan Smit")]


def test_fold_drops_titles_accents_and_punctuation() -> None:
    assert fold("Dhr. José  van der Berg") == "jose van der berg"


@pytest.mark.parametrize("written", ["Anna de Vries", "anna  de vries", "de Vries, Anna", "Mevr. Anna de Vries"])
def test_name_variants_match(written: str) -> None:
    found = match_name(written, PEOPLE)
    assert found.ref_id == ANNA
    assert not found.ambiguous


def test_close_but_different_people_are_not_confused() -> None:
    assert match_name("Anne de Vos", PEOPLE).ref_id == ANNE


def test_single_first_name_never_matches() -> None:
    found = match_name("Jan", PEOPLE)
    assert found.ref_id is None
    assert not found.ambiguous


def test_unknown_name_matches_nothing() -> None:
    assert match_name("Pieter Jansen", PEOPLE).ref_id is None


def test_equal_candidates_are_ambiguous_not_guessed() -> None:
    twins = [(uuid4(), "Piet de Boer"), (uuid4(), "Piet de Boer")]
    found = match_name("Piet de Boer", twins)
    assert found.ref_id is None
    assert found.ambiguous


U12_1, U12_2, U7 = uuid4(), uuid4(), uuid4()
UNITS = [
    (U12_1, "Kerkstraat 12-1", "Kerkstraat 12-1, 1015 AB Amsterdam"),
    (U12_2, "Kerkstraat 12-2", "Kerkstraat 12-2, 1015 AB Amsterdam"),
    (U7, "Zeestraat 7", None),
]


def test_exact_unit_address_matches() -> None:
    assert match_unit("Kerkstraat 12-2, Amsterdam", UNITS).ref_id == U12_2
    assert match_unit("zeestraat 7", UNITS).ref_id == U7


def test_hint_that_fits_several_units_is_ambiguous() -> None:
    found = match_unit("Kerkstraat 12", UNITS)
    assert found.ref_id is None
    assert found.ambiguous


def test_unknown_address_matches_nothing() -> None:
    assert match_unit("Dorpsweg 99", UNITS).ref_id is None


def test_active_lease_needs_exactly_one_valid_lease() -> None:
    old, new = uuid4(), uuid4()
    leases = [(old, date(2020, 1, 1), date(2024, 12, 31)), (new, date(2025, 1, 1), None)]
    assert active_lease(leases, date(2026, 5, 1)) == new
    assert active_lease(leases, date(2022, 5, 1)) == old
    assert active_lease(leases, date(2019, 5, 1)) is None
    assert active_lease([*leases, (uuid4(), date(2025, 6, 1), None)], date(2026, 5, 1)) is None

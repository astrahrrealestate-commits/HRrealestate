"""Layout v2 rules (pure): folder names from unit labels, kind folders, Drive property limits."""

from datetime import date

import pytest

from app.contracts import DocType
from app.pipeline.document_layout import (
    KIND_FOLDER,
    LAYOUT_VERSION,
    UNSORTED,
    description,
    drive_properties,
    folder_name,
    folder_path_v2,
    kind_folder,
)


def test_every_doc_type_has_a_kind_folder() -> None:
    assert set(KIND_FOLDER) == set(DocType)
    assert len(set(KIND_FOLDER.values())) == len(DocType)


def test_path_is_root_unit_kind_year() -> None:
    assert folder_path_v2("lease", "Kerkstraat 12-2", date(2026, 3, 1)) == (
        "EstateOS",
        "Kerkstraat 12-2",
        "Leases",
        "2026",
    )
    assert folder_path_v2("invoice", None, date(2025, 12, 31)) == ("EstateOS", UNSORTED, "Invoices", "2025")


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Kerkstraat 12-2", "Kerkstraat 12-2"),
        ("  Unit  3 ", "Unit 3"),
        ("A/B\\C", "A B C"),  # a path separator never splits the stored folder path
        ("../../etc", "etc"),
        ("", UNSORTED),
        (None, UNSORTED),
        ("   ", UNSORTED),
        ("..", UNSORTED),
        (UNSORTED, UNSORTED),
        ("x" * 200, "x" * 60),
        ("Straat\n12", "Straat 12"),
    ],
)
def test_folder_name_is_one_safe_segment(label: str | None, expected: str) -> None:
    got = folder_name(label)
    assert got == expected
    assert "/" not in got
    assert "\\" not in got


def test_unknown_doc_type_falls_back_to_other() -> None:
    assert kind_folder("hologram") == "Other"


def test_drive_properties_are_short_and_clipped_on_byte_boundaries() -> None:
    props = drive_properties("lease", "é" * 100, "anna-de-vries", date(2026, 1, 2))
    assert props["layout"] == LAYOUT_VERSION
    assert props["date"] == "2026-01-02"
    assert props["party"] == "anna-de-vries"
    for key, value in props.items():
        assert len(key.encode()) + len(value.encode()) <= 124
    assert "unit" not in drive_properties("lease", None, None, date(2026, 1, 2))
    assert "party" not in drive_properties("lease", "U", None, date(2026, 1, 2))


def test_description_prefers_the_summary_and_is_bounded() -> None:
    assert description("Titel", "Samenvatting\nover twee regels") == "Samenvatting over twee regels"
    assert description("Titel", None) == "Titel"
    assert len(description("t", "x" * 1000)) == 400

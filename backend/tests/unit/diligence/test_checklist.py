"""Checklist: what the framework asks for against what the documents are."""

from datetime import date

from app.contracts.diligence import DDDocKind as K
from app.contracts.diligence import DDField, DDPropertyKind
from app.contracts.diligence_report import ChecklistStatus as St
from app.diligence.checklist import build_checklist
from app.diligence.framework import default_framework
from tests.unit.diligence.builders import TODAY, doc, num, txt, unreadable

FW = default_framework()


def _status(items, key):  # type: ignore[no-untyped-def]
    return next(i for i in items if i.key == key).status


def test_missing_when_no_document_of_an_accepted_kind() -> None:
    items = build_checklist(FW, DDPropertyKind.apartment, [doc(K.brochure)], TODAY)
    assert _status(items, "kadaster") is St.missing
    assert _status(items, "brochure") is St.present


def test_either_accepted_kind_satisfies_the_requirement() -> None:
    for kind in (K.deed_of_title, K.purchase_agreement):
        items = build_checklist(FW, DDPropertyKind.house, [doc(kind)], TODAY)
        assert _status(items, "title") is St.present


def test_vve_items_do_not_apply_to_a_house() -> None:
    keys = {i.key for i in build_checklist(FW, DDPropertyKind.house, [], TODAY)}
    assert "vve_rules" not in keys
    assert "house_survey" in keys


def test_tenanted_investment_adds_leases_and_rent_roll() -> None:
    keys = {i.key for i in build_checklist(FW, DDPropertyKind.tenanted_investment, [], TODAY)}
    assert {"leases", "rent_roll", "vve_rules"} <= keys


def test_ground_lease_required_only_when_leasehold_is_stated() -> None:
    plain = build_checklist(FW, DDPropertyKind.house, [doc(K.brochure, txt(DDField.ownership_type, "freehold"))], TODAY)
    assert "ground_lease" not in {i.key for i in plain}
    leasehold = doc(K.deed_of_title, txt(DDField.ownership_type, "leasehold"))
    assert _status(build_checklist(FW, DDPropertyKind.house, [leasehold], TODAY), "ground_lease") is St.missing
    both = [leasehold, doc(K.ground_lease)]
    assert _status(build_checklist(FW, DDPropertyKind.house, both, TODAY), "ground_lease") is St.present


def test_asbestos_report_required_before_1994_and_when_year_unknown() -> None:
    old = build_checklist(FW, DDPropertyKind.house, [doc(K.brochure, num(DDField.year_built, "1965"))], TODAY)
    assert _status(old, "asbestos") is St.missing
    unknown = build_checklist(FW, DDPropertyKind.house, [], TODAY)
    assert _status(unknown, "asbestos") is St.missing
    new = build_checklist(FW, DDPropertyKind.house, [doc(K.brochure, num(DDField.year_built, "2005"))], TODAY)
    assert "asbestos" not in {i.key for i in new}


def test_old_document_is_stale() -> None:
    old = doc(K.vve_minutes, document_date=date(2024, 1, 10))
    fresh = doc(K.vve_minutes, document_date=date(2026, 5, 1))
    assert _status(build_checklist(FW, DDPropertyKind.apartment, [old], TODAY), "vve_minutes") is St.stale
    assert _status(build_checklist(FW, DDPropertyKind.apartment, [old, fresh], TODAY), "vve_minutes") is St.present


def test_expired_validity_is_stale_even_when_recent() -> None:
    label = doc(K.energy_label, document_date=date(2020, 1, 1), valid_until=date(2026, 1, 1))
    assert _status(build_checklist(FW, DDPropertyKind.house, [label], TODAY), "energy_label") is St.stale


def test_undated_document_with_an_age_limit_is_unclear() -> None:
    item = next(
        i for i in build_checklist(FW, DDPropertyKind.house, [doc(K.energy_label)], TODAY) if i.key == "energy_label"
    )
    assert item.status is St.unclear
    assert item.note is not None
    assert "undated" in item.note.lower()


def test_undated_document_with_a_future_validity_date_is_present() -> None:
    label = doc(K.energy_label, valid_until=date(2030, 1, 1))
    assert _status(build_checklist(FW, DDPropertyKind.house, [label], TODAY), "energy_label") is St.present


def test_a_dated_fresh_document_beats_an_undated_one() -> None:
    docs = [doc(K.vve_minutes), doc(K.vve_minutes, document_date=date(2026, 5, 1))]
    assert _status(build_checklist(FW, DDPropertyKind.apartment, docs, TODAY), "vve_minutes") is St.present


def test_leasehold_in_any_top_authority_document_requires_ground_lease_papers() -> None:
    docs = [
        doc(K.deed_of_title, txt(DDField.ownership_type, "freehold")),
        doc(K.purchase_agreement, txt(DDField.ownership_type, "erfpacht")),
    ]
    assert _status(build_checklist(FW, DDPropertyKind.house, docs, TODAY), "ground_lease") is St.missing


def test_low_confidence_read_is_unclear_not_present() -> None:
    item = build_checklist(FW, DDPropertyKind.house, [doc(K.kadaster_extract, confidence=0.3)], TODAY)
    assert _status(item, "kadaster") is St.unclear


def test_unreadable_document_satisfies_nothing() -> None:
    items = build_checklist(FW, DDPropertyKind.house, [unreadable()], TODAY)
    assert all(i.status is St.missing for i in items)

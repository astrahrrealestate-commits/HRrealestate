"""Mismatches: same fact, different value; a brochure against an official or legal document ranks higher."""

from datetime import date

from app.contracts.diligence import DDDocKind as K
from app.contracts.diligence import DDField as F
from app.contracts.diligence_report import DDSeverity, MismatchKind
from app.diligence.compare import find_mismatches
from app.diligence.framework import default_framework
from tests.unit.diligence.builders import day, doc, num, txt

FW = default_framework()


def test_area_within_tolerance_is_not_a_mismatch() -> None:
    docs = [doc(K.brochure, num(F.living_area_m2, "85")), doc(K.deed_of_title, num(F.living_area_m2, "84"))]
    assert find_mismatches(FW, docs) == []


def test_brochure_area_against_deed_is_marketing_vs_legal_high() -> None:
    brochure = doc(K.brochure, num(F.living_area_m2, "95", "Woonoppervlakte 95 m2"), title="Brochure")
    deed = doc(K.deed_of_title, num(F.living_area_m2, "82", "gebruiksoppervlakte 82 m2"), title="Akte")
    [m] = find_mismatches(FW, [brochure, deed])
    assert m.kind is MismatchKind.marketing_vs_legal
    assert m.severity is DDSeverity.high
    assert m.reference.document_id == deed.document_id
    assert m.other.document_id == brochure.document_id
    assert m.reference.quote == "gebruiksoppervlakte 82 m2"
    assert "95" in m.difference
    assert "82" in m.difference


def test_reference_is_the_more_authoritative_whatever_the_input_order() -> None:
    brochure = doc(K.brochure, num(F.year_built, "1985"))
    deed = doc(K.purchase_agreement, num(F.year_built, "1965"))
    for docs in ([brochure, deed], [deed, brochure]):
        [m] = find_mismatches(FW, docs)
        assert m.reference.document_id == deed.document_id


def test_price_mismatch_is_medium_because_asking_differs_from_agreed() -> None:
    docs = [doc(K.brochure, num(F.price, "450000")), doc(K.purchase_agreement, num(F.price, "425000"))]
    [m] = find_mismatches(FW, docs)
    assert m.kind is MismatchKind.marketing_vs_legal
    assert m.severity is DDSeverity.medium


def test_two_legal_documents_disagreeing_is_inconsistent_medium() -> None:
    docs = [doc(K.deed_of_title, num(F.plot_area_m2, "120")), doc(K.kadaster_extract, num(F.plot_area_m2, "98"))]
    [m] = find_mismatches(FW, docs)
    assert m.kind is MismatchKind.inconsistent
    assert m.severity is DDSeverity.medium


def test_energy_label_compared_exactly_and_case_insensitively() -> None:
    same = [doc(K.brochure, txt(F.energy_label, "b")), doc(K.energy_label, txt(F.energy_label, "B"))]
    assert find_mismatches(FW, same) == []
    differ = [doc(K.brochure, txt(F.energy_label, "A")), doc(K.energy_label, txt(F.energy_label, "D"))]
    assert len(find_mismatches(FW, differ)) == 1


def test_ownership_synonyms_are_normalised() -> None:
    same = [doc(K.brochure, txt(F.ownership_type, "eigendom")), doc(K.deed_of_title, txt(F.ownership_type, "freehold"))]
    assert find_mismatches(FW, same) == []
    differ = [
        doc(K.brochure, txt(F.ownership_type, "volle eigendom")),
        doc(K.deed_of_title, txt(F.ownership_type, "erfpacht")),
    ]
    [m] = find_mismatches(FW, differ)
    assert m.kind is MismatchKind.marketing_vs_legal


def test_address_ignores_case_and_punctuation() -> None:
    docs = [doc(K.brochure, txt(F.address, "Kerkstraat 12-2")), doc(K.deed_of_title, txt(F.address, "kerkstraat 12 2"))]
    assert find_mismatches(FW, docs) == []


def test_dates_compare_exactly() -> None:
    docs = [
        doc(K.brochure, day(F.ground_lease_end, date(2060, 1, 1))),
        doc(K.ground_lease, day(F.ground_lease_end, date(2045, 1, 1))),
    ]
    [m] = find_mismatches(FW, docs)
    assert m.field is F.ground_lease_end


def test_unreadable_and_low_confidence_documents_are_not_compared() -> None:
    low = doc(K.deed_of_title, num(F.year_built, "1900"), confidence=0.2)
    assert find_mismatches(FW, [doc(K.brochure, num(F.year_built, "1985")), low]) == []


def test_two_documents_agreeing_against_one_report_one_mismatch_per_disagreeing_document() -> None:
    deed = doc(K.deed_of_title, num(F.year_built, "1965"))
    docs = [deed, doc(K.brochure, num(F.year_built, "1985")), doc(K.valuation, num(F.year_built, "1965"))]
    assert len(find_mismatches(FW, docs)) == 1


def test_the_same_document_stating_two_values_is_inconsistent() -> None:
    d = doc(K.brochure, num(F.living_area_m2, "85"), num(F.living_area_m2, "100"))
    [m] = find_mismatches(FW, [d])
    assert m.kind is MismatchKind.inconsistent


def test_equal_authority_disagreement_on_a_critical_field_is_high() -> None:
    docs = [
        doc(K.deed_of_title, day(F.ground_lease_end, date(2060, 1, 1))),
        doc(K.ground_lease, day(F.ground_lease_end, date(2030, 1, 1))),
    ]
    [m] = find_mismatches(FW, docs)
    assert m.kind is MismatchKind.inconsistent
    assert m.severity is DDSeverity.high

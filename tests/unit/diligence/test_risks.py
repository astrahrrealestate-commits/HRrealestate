"""Rule-based risks and document-quoted flags."""

from datetime import date

from app.contracts.diligence import DDDocKind as K
from app.contracts.diligence import DDField as F
from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DDSeverity as Sev
from app.diligence.framework import default_framework
from app.diligence.risks import find_risks
from tests.unit.diligence.builders import TODAY, day, doc, flag, num, txt, unreadable

FW = default_framework()


def _by_code(risks, code):  # type: ignore[no-untyped-def]
    return [r for r in risks if r.code == code]


def test_ground_lease_ending_in_under_15_years_is_high() -> None:
    docs = [doc(K.ground_lease, day(F.ground_lease_end, date(2038, 6, 1)))]
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, docs, TODAY), "ground_lease_ending")
    assert r.severity is Sev.high


def test_ground_lease_ending_in_15_to_30_years_is_medium() -> None:
    docs = [doc(K.ground_lease, day(F.ground_lease_end, date(2050, 1, 1)))]
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, docs, TODAY), "ground_lease_ending")
    assert r.severity is Sev.medium


def test_ground_lease_beyond_30_years_is_no_risk() -> None:
    docs = [doc(K.ground_lease, day(F.ground_lease_end, date(2070, 1, 1)))]
    assert _by_code(find_risks(FW, DDPropertyKind.house, docs, TODAY), "ground_lease_ending") == []


def test_energy_label_f_and_g_high_e_medium_c_none() -> None:
    expected = {"G": Sev.high, "F": Sev.high, "E": Sev.medium}
    for label, sev in expected.items():
        [r] = _by_code(
            find_risks(FW, DDPropertyKind.house, [doc(K.energy_label, txt(F.energy_label, label))], TODAY),
            "low_energy_label",
        )
        assert r.severity is sev
    ok = find_risks(FW, DDPropertyKind.house, [doc(K.energy_label, txt(F.energy_label, "C"))], TODAY)
    assert _by_code(ok, "low_energy_label") == []


def test_asbestos_present_is_high() -> None:
    docs = [doc(K.asbestos_report, txt(F.asbestos, "present", "asbest aangetroffen"))]
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, docs, TODAY), "asbestos_present")
    assert r.severity is Sev.high


def test_asbestos_absent_is_no_risk() -> None:
    docs = [doc(K.asbestos_report, txt(F.asbestos, "absent"))]
    assert _by_code(find_risks(FW, DDPropertyKind.house, docs, TODAY), "asbestos_present") == []


def test_pre_1945_without_survey_is_medium_and_survey_clears_it() -> None:
    brochure = doc(K.brochure, num(F.year_built, "1930"))
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, [brochure], TODAY), "old_building_no_survey")
    assert r.severity is Sev.medium
    with_survey = find_risks(FW, DDPropertyKind.house, [brochure, doc(K.building_survey)], TODAY)
    assert _by_code(with_survey, "old_building_no_survey") == []


def test_expired_document_is_medium() -> None:
    expired = doc(K.insurance, valid_until=date(2026, 6, 30))
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, [expired], TODAY), "document_expired")
    assert r.severity is Sev.medium
    assert r.document_ids == [expired.document_id]


def test_tenancy_ending_within_a_year_only_for_tenanted_investment() -> None:
    lease = doc(K.lease_agreement, day(F.tenancy_end, date(2027, 6, 30)))
    risks = find_risks(FW, DDPropertyKind.tenanted_investment, [lease], TODAY)
    assert len(_by_code(risks, "tenancy_ending")) == 1
    assert _by_code(find_risks(FW, DDPropertyKind.house, [lease], TODAY), "tenancy_ending") == []
    later = doc(K.lease_agreement, day(F.tenancy_end, date(2029, 1, 1)))
    assert _by_code(find_risks(FW, DDPropertyKind.tenanted_investment, [later], TODAY), "tenancy_ending") == []


def test_document_flag_becomes_a_medium_document_risk_with_its_quote() -> None:
    minutes = doc(K.vve_minutes, flags=(flag(),))
    [r] = _by_code(find_risks(FW, DDPropertyKind.apartment, [minutes], TODAY), "document_flag_legal")
    assert r.severity is Sev.medium
    assert r.source == "document"
    assert r.quote == "geschil met de VvE"


def test_unreadable_documents_are_one_medium_risk() -> None:
    a, b = unreadable("a.pdf"), unreadable("b.pdf")
    [r] = _by_code(find_risks(FW, DDPropertyKind.house, [a, b], TODAY), "unreadable_documents")
    assert r.severity is Sev.medium
    assert set(r.document_ids) == {a.document_id, b.document_id}


def test_the_reference_value_is_the_most_authoritative_claim() -> None:
    brochure = doc(K.brochure, txt(F.energy_label, "A"))
    label = doc(K.energy_label, txt(F.energy_label, "G"))
    assert _by_code(find_risks(FW, DDPropertyKind.house, [brochure, label], TODAY), "low_energy_label")

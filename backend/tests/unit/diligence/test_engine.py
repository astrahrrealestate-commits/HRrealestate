"""The whole screen: verdict, coverage, and the report's shape."""

from datetime import date

from app.contracts.diligence import DDDocKind as K
from app.contracts.diligence import DDField as F
from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import DISCLAIMER, DDReport, DDVerdict
from app.diligence.engine import screen
from app.diligence.framework import default_framework
from tests.unit.diligence.builders import TODAY, day, doc, num, txt, unreadable

FW = default_framework()


def _complete_house() -> list:  # type: ignore[type-arg]
    return [
        doc(K.deed_of_title, num(F.year_built, "2005"), num(F.living_area_m2, "120")),
        doc(K.kadaster_extract),
        doc(K.energy_label, txt(F.energy_label, "B"), document_date=date(2024, 3, 1)),
        doc(K.building_survey),
        doc(K.brochure, num(F.living_area_m2, "120")),
        doc(K.permit),
    ]


def test_complete_consistent_pile_is_clear_to_review() -> None:
    report = screen(FW, DDPropertyKind.house, _complete_house(), TODAY, unverified=0)
    assert report.verdict is DDVerdict.clear_to_review
    assert report.coverage.present == report.coverage.applicable
    assert report.mismatches == []
    assert report.disclaimer == DISCLAIMER


def test_missing_critical_document_needs_documents() -> None:
    docs = [d for d in _complete_house() if d.read and d.read.doc_kind is not K.kadaster_extract]
    report = screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0)
    assert report.verdict is DDVerdict.needs_documents
    assert report.coverage.present < report.coverage.applicable


def test_missing_only_nice_to_have_stays_clear() -> None:
    docs = [d for d in _complete_house() if d.read and d.read.doc_kind is not K.brochure]
    assert screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).verdict is DDVerdict.clear_to_review


def test_high_mismatch_is_red_flags_even_with_documents_missing() -> None:
    docs = [
        doc(K.deed_of_title, num(F.year_built, "1965")),
        doc(K.brochure, num(F.year_built, "1995")),
    ]
    assert screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).verdict is DDVerdict.red_flags


def test_high_risk_is_red_flags() -> None:
    docs = [*_complete_house(), doc(K.ground_lease, day(F.ground_lease_end, date(2035, 1, 1)))]
    assert screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).verdict is DDVerdict.red_flags


def test_no_documents_needs_documents_and_is_never_clear() -> None:
    report = screen(FW, DDPropertyKind.house, [], TODAY, unverified=0)
    assert report.verdict is DDVerdict.needs_documents
    assert report.coverage.present == 0


def test_only_unreadable_documents_is_needs_documents() -> None:
    report = screen(FW, DDPropertyKind.house, [unreadable()], TODAY, unverified=0)
    assert report.verdict is DDVerdict.needs_documents
    assert [d.readable for d in report.documents] == [False]
    assert report.documents[0].doc_kind is None


def test_unverified_count_is_reported() -> None:
    assert screen(FW, DDPropertyKind.house, [], TODAY, unverified=3).unverified_claims == 3


def test_report_is_stable_json_and_round_trips() -> None:
    report = screen(FW, DDPropertyKind.apartment, _complete_house(), TODAY, unverified=1)
    again = DDReport.model_validate(report.model_dump(mode="json"))
    assert again == report
    assert (
        screen(FW, DDPropertyKind.apartment, _complete_house(), TODAY, unverified=1).framework_version
        == "nl-residential-v1"
    )


def test_findings_are_ordered_high_severity_first() -> None:
    docs = [
        doc(K.energy_label, txt(F.energy_label, "E")),
        doc(K.asbestos_report, txt(F.asbestos, "present")),
    ]
    severities = [r.severity.value for r in screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).risks]
    assert severities == sorted(severities, key=["high", "medium", "low"].index)


def test_feed_payload_is_compact_and_names_the_gaps() -> None:
    from uuid import uuid4

    from app.diligence.summary import feed_payload

    docs = [d for d in _complete_house() if d.read and d.read.doc_kind is not K.kadaster_extract]
    report = screen(FW, DDPropertyKind.house, docs, TODAY, unverified=2)
    review_id = uuid4()
    payload = feed_payload(review_id, "Kerkstraat 12", report)
    assert payload["review_id"] == str(review_id)
    assert payload["title"] == "Kerkstraat 12"
    assert payload["verdict"] == "needs_documents"
    assert payload["missing"] == ["Kadaster extract"]
    assert payload["coverage"] == {"present": report.coverage.present, "applicable": report.coverage.applicable}
    assert payload["counts"] == {"mismatches": 0, "high_risks": 0, "risks": 0}


def test_unverified_claims_block_clear_to_review() -> None:
    assert screen(FW, DDPropertyKind.house, _complete_house(), TODAY, unverified=1).verdict is DDVerdict.needs_documents


def test_an_unreadable_document_blocks_clear_to_review() -> None:
    docs = [*_complete_house(), unreadable()]
    assert screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).verdict is DDVerdict.needs_documents


def test_a_truncated_document_blocks_clear_to_review() -> None:
    from dataclasses import replace

    docs = _complete_house()
    docs[0] = replace(docs[0], truncated=True)
    assert screen(FW, DDPropertyKind.house, docs, TODAY, unverified=0).verdict is DDVerdict.needs_documents

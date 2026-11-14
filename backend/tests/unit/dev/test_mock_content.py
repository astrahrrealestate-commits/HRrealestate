"""The mock portfolio: readable PDFs, phone numbers in the reserved range, and a report that lists every agent."""

import io

from pypdf import PdfReader

from app.dev import mock_content as mc
from app.dev import mock_report


def test_every_document_reads_back_with_its_key_facts() -> None:
    facts = {
        "offerte_2026-117.pdf": "480,00",
        "factuur_2026-0931.pdf": "1.089,00",
        "huurovereenkomst_prinsengracht-118-B.pdf": "opzegging",
        "energielabel_keizersgracht-42-A.pdf": "Energielabel: D",
        "notulen_vve_2026.pdf": "14.500",
    }
    assert set(facts) == set(mc.DOCUMENTS)
    for name, needle in facts.items():
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(mc.pdf(name).data)).pages)
        assert needle.lower() in text.lower(), name


def test_phone_numbers_are_unique_and_in_the_reserved_range() -> None:
    phones = [p.phone for p in mc.PEOPLE]
    assert len(set(phones)) == len(phones)
    assert all(p.startswith("+3165550") for p in phones)


def test_every_tenant_rents_a_known_unit_and_contractors_have_a_trade() -> None:
    for person in mc.PEOPLE:
        if person.kind == "tenant":
            assert person.unit in mc.UNITS
        else:
            assert person.trade


def test_report_lists_every_agent_and_marks_the_missing_ones_zero() -> None:
    text = mock_report.render({"triage": mock_report.Calls("triage", 3, 1)}, {"cases": 2})
    assert "triage" in text
    assert "dd_reader" in text
    assert text.count("\n") > len(mock_report.AGENTS)

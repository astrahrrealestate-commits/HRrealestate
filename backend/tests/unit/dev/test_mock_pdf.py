"""The mock PDF builder: the text it writes is the text the pipeline's extractor reads back."""

import io

from pypdf import PdfReader

from app.dev.mock_pdf import text_pdf


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def test_lines_survive_a_round_trip_through_pypdf() -> None:
    lines = ["OFFERTE 2026-117", "Totaal incl. btw: EUR 1.210,00", "Betaling binnen 14 dagen"]
    text = _text(text_pdf(lines))
    assert all(line in text for line in lines)


def test_parentheses_backslashes_and_the_euro_sign_are_escaped() -> None:
    line = r"Prijs (excl. btw) \ € 480,00"
    assert line in _text(text_pdf([line]))


def test_long_documents_continue_on_further_pages() -> None:
    pdf = text_pdf([f"regel {i}" for i in range(130)])
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 3
    assert "regel 129" in _text(pdf)


def test_the_output_is_a_pdf() -> None:
    assert text_pdf(["x"]).startswith(b"%PDF-1.4")

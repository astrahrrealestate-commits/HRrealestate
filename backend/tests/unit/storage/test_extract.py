"""M10 text extraction: PDF/docx/plain, scan detection, caps, no crash on hostile input."""

import io
import zipfile

import pytest

from app.db.enums import ExtractionStatus
from app.pipeline.document_policy import FileMeta, looks_like_id
from app.storage import extract
from app.storage.extract import FakeExtractor, LocalExtractor

LEASE_TEXT = "Huurovereenkomst woonruimte. De waarborgsom bedraagt twee maanden kale huur. Opzegtermijn drie maanden."
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one text line per page with a real xref table."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    for i, line in enumerate(pages):
        content_no = 4 + 2 * i
        res = "/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >>"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_no} 0 R {res} >>")
        stream = f"BT /F1 10 Tf 20 700 Td ({line}) Tj ET" if line else ""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = "%PDF-1.4\n"
    offsets = []
    for n, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{obj}\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Root 1 0 R /Size {len(objs) + 1} >>\nstartxref\n{xref_at}\n%%EOF"
    return out.encode()


def make_docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


def make_xlsx(rows: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        body = "".join(
            "<row>" + "".join(f'<c t="inlineStr"><is><t>{cell}</t></is></c>' for cell in row) + "</row>" for row in rows
        )
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{body}</sheetData></worksheet>")
    return buf.getvalue()


def test_xlsx_and_octet_stream_filename_fallback() -> None:
    xlsx_bytes = make_xlsx([["Eenheid", "Huur"], ["Singel 5", "1850"]])
    got_xlsx = LocalExtractor().extract(xlsx_bytes, "application/octet-stream", "huurlijst.xlsx")
    assert got_xlsx.status is ExtractionStatus.done
    assert got_xlsx.text == "Eenheid | Huur\nSingel 5 | 1850"

    got_pdf = LocalExtractor().extract(make_pdf([LEASE_TEXT]), "application/octet-stream", "huur.pdf")
    assert got_pdf.status is ExtractionStatus.done
    assert got_pdf.text is not None
    assert "waarborgsom" in got_pdf.text

    got_scan = LocalExtractor().extract(b"\xff\xd8data", "application/octet-stream", "foto.jpg")
    assert got_scan.needs_ocr is True


def test_text_pdf_is_read() -> None:
    got = LocalExtractor().extract(make_pdf([LEASE_TEXT]), PDF, "huur.pdf")
    assert got.status is ExtractionStatus.done
    assert got.text is not None
    assert "waarborgsom" in got.text
    assert got.page_count == 1
    assert got.extractor == "pypdf"
    assert not got.needs_ocr


def test_pdf_without_text_layer_needs_vision() -> None:
    got = LocalExtractor().extract(make_pdf([""]), PDF, "scan.pdf")
    assert got.status is ExtractionStatus.skipped
    assert got.needs_ocr
    assert got.text is None


def test_pdf_over_page_cap_is_skipped_not_read() -> None:
    got = LocalExtractor().extract(make_pdf([LEASE_TEXT] * (extract.MAX_PAGES + 1)), PDF, None)
    assert got.status is ExtractionStatus.skipped
    assert got.text is None
    assert got.page_count == extract.MAX_PAGES + 1


def test_corrupt_pdf_is_failed_without_raising() -> None:
    got = LocalExtractor().extract(b"%PDF-1.4 not really", PDF, "x.pdf")
    assert got.status is ExtractionStatus.failed
    assert got.text is None


def test_docx_text_and_paragraphs() -> None:
    got = LocalExtractor().extract(make_docx(["Offerte dakreparatie", "Totaal &amp; btw: 1.250,00"]), DOCX, "o.docx")
    assert got.status is ExtractionStatus.done
    assert got.text == "Offerte dakreparatie\nTotaal & btw: 1.250,00"


def test_broken_docx_is_failed() -> None:
    assert LocalExtractor().extract(b"PK nope", DOCX, "x.docx").status is ExtractionStatus.failed


def test_plain_text_and_empty() -> None:
    assert LocalExtractor().extract(b"Hallo  wereld\n\n\n\nbye", "text/plain", None).text == "Hallo wereld\n\nbye"
    assert LocalExtractor().extract(b"   ", "text/plain", None).status is ExtractionStatus.skipped


@pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/heic"])
def test_images_are_handed_to_vision(mime: str) -> None:
    got = LocalExtractor().extract(b"\xff\xd8data", mime, "foto.jpg")
    assert got.status is ExtractionStatus.skipped
    assert got.needs_ocr


def test_unknown_type_and_oversize_are_skipped() -> None:
    assert LocalExtractor().extract(b"x", "application/zip", None).status is ExtractionStatus.skipped
    big = LocalExtractor().extract(b"x" * (extract.MAX_BYTES + 1), PDF, None)
    assert big.status is ExtractionStatus.skipped
    assert big.note == "file too large"


def test_text_is_capped() -> None:
    got = LocalExtractor().extract(("a" * 1000 + "\n").encode() * 300, "text/plain", None)
    assert got.text is not None
    assert len(got.text) == extract.MAX_CHARS


def test_fake_extractor() -> None:
    assert FakeExtractor().extract(LEASE_TEXT.encode(), PDF, None).text == LEASE_TEXT
    assert FakeExtractor().extract(b"SCAN-1", PDF, None).needs_ocr


@pytest.mark.parametrize(
    ("name", "expected"),
    [("paspoort_jan.pdf", True), ("ID-kaart.jpg", True), ("Rijbewijs.png", True), ("passport.pdf", True),
     ("huurovereenkomst.pdf", False), ("factuur_idee.pdf", False), (None, False)],
)  # fmt: skip
def test_id_document_names_are_never_read(name: str | None, expected: bool) -> None:
    from datetime import UTC, datetime

    assert looks_like_id(FileMeta(name, PDF, 100, datetime(2026, 1, 1, tzinfo=UTC))) is expected

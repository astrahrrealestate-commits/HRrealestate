from app.db.enums import DocumentStatus
from app.dev.demo_documents import INVOICE, PHOTO, DocRow, document_problems


def _invoice(status: DocumentStatus = DocumentStatus.filed, doc_type: str = "invoice") -> DocRow:
    return DocRow(INVOICE.filename, status, doc_type, f"2026-10-08_{doc_type}_mevr-de-vries_invoice.pdf", "file-1")


def _photo(status: DocumentStatus = DocumentStatus.review) -> DocRow:
    return DocRow(PHOTO.filename, status, "photo", "2026-10-08_photo_mevr-de-vries_photo.jpg", None)


def test_expected_outcome_has_no_problems() -> None:
    assert document_problems([_invoice(), _photo()]) == []


def test_missing_rows_and_wrong_statuses_are_reported() -> None:
    assert document_problems([]) == [
        f"documents: no row for {INVOICE.filename}",
        f"documents: no row for {PHOTO.filename}",
    ]
    problems = document_problems([_invoice(DocumentStatus.review), _photo(DocumentStatus.filed)])
    assert len(problems) == 2


def test_invoice_filed_under_the_wrong_type_is_reported() -> None:
    assert document_problems([_invoice(doc_type="other"), _photo()]) == [
        "documents: invoice filed wrongly (other, 2026-10-08_other_mevr-de-vries_invoice.pdf)"
    ]


def test_demo_attachments_pass_the_skip_rules() -> None:
    from datetime import UTC, datetime

    from app.pipeline.document_policy import FileMeta, should_skip

    for att in (INVOICE, PHOTO):
        meta = FileMeta(att.filename, att.mime_type, len(att.data), datetime(2026, 10, 8, tzinfo=UTC))
        assert not should_skip(meta), att.filename

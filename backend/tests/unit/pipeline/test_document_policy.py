from datetime import UTC, date, datetime

import pytest

from app.contracts import DocType, DocumentClassification
from app.db.enums import DocumentStatus
from app.pipeline.document_policy import (
    FileMeta,
    file_name,
    filing_status,
    folder_path,
    looks_like_finance_text,
    name_date,
    should_skip,
)

AMS = "Europe/Amsterdam"
SENT = datetime(2026, 10, 6, 23, 30, tzinfo=UTC)  # 7 Oct in Amsterdam


def meta(name: str | None, mime: str = "application/pdf", size: int = 100_000) -> FileMeta:
    return FileMeta(filename=name, mime_type=mime, size_bytes=size, sent_at=SENT)


def cls(conf: float = 0.9, day: date | None = None, title: str = "Factuur Loodgieter Één") -> DocumentClassification:
    return DocumentClassification(doc_type=DocType.invoice, title=title, document_date=day, confidence=conf)


def test_name_uses_local_sent_date_slugs_and_extension() -> None:
    assert file_name(cls(), meta("Scan 01.PDF"), "Mevr. de Vries", AMS) == (
        "2026-10-07_invoice_mevr-de-vries_factuur-loodgieter-een.pdf"
    )


def test_name_prefers_document_date_and_mime_extension() -> None:
    got = file_name(cls(day=date(2026, 9, 1)), meta(None, "image/jpeg"), "", AMS)
    assert got == "2026-09-01_invoice_unknown_factuur-loodgieter-een.jpg"


def test_name_never_contains_path_tricks() -> None:
    got = file_name(cls(title="../../etc/passwd"), meta("x.exe/../../a.pdf"), "a/b\\c", AMS)
    assert "/" not in got
    assert "\\" not in got
    assert ".." not in got
    assert got == "2026-10-07_invoice_a-b-c_etc-passwd.pdf"


def test_name_caps_long_parts() -> None:
    got = file_name(cls(title="t" * 80), meta("a.pdf"), "p" * 100, AMS)
    assert len(got) <= 120


def test_folder_path() -> None:
    assert folder_path(cls(), meta("a.pdf"), AMS) == ("EstateOS", "invoice", "2026")


@pytest.mark.parametrize(("conf", "status"), [(0.8, DocumentStatus.filed), (0.79, DocumentStatus.review)])
def test_confidence_gate(conf: float, status: DocumentStatus) -> None:
    assert filing_status(cls(conf=conf)) is status


@pytest.mark.parametrize(
    ("name", "mime", "size", "skip"),
    [
        ("logo.png", "image/png", 5_000, True),
        ("lekkage.jpg", "image/jpeg", 300_000, False),
        ("invite.ics", "text/calendar", 2_000, True),
        ("signature.asc", "application/pgp-signature", 900, True),
        ("factuur.pdf", "application/pdf", 1_000, False),
        ("opmerkingen.txt", "text/plain", 400, False),
        ("huurlijst.csv", "text/csv", 400, False),
        (None, "text/plain", 400, True),
        (None, "application/octet-stream", 0, True),
    ],
)
def test_skip_rules(name: str | None, mime: str, size: int, skip: bool) -> None:
    assert should_skip(meta(name, mime, size)) is skip


@pytest.mark.parametrize(
    ("name", "mime", "ext"),
    [
        ("factuur.pdf.exe", "application/pdf", "pdf"),
        ("payload.exe", "application/octet-stream", "bin"),
        ("rooster.xlsx", "application/octet-stream", "xlsx"),
        ("brief.DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    ],
)
def test_extension_trusts_mime_then_allowlist(name: str, mime: str, ext: str) -> None:
    assert file_name(cls(), meta(name, mime), "p", AMS).endswith(f".{ext}")


def test_name_date() -> None:
    assert name_date("2026-09-01_invoice_jan_x.pdf") == date(2026, 9, 1)
    assert name_date("") is None
    assert name_date("garbage") is None


def test_parse_name_knows_kinds_with_an_underscore() -> None:
    from app.pipeline.document_policy import parse_name

    assert parse_name("2026-10-21_id_document_jan-jansen_paspoort.pdf") == (
        "2026-10-21", "id_document", "jan-jansen", "paspoort", "pdf"
    )  # fmt: skip
    assert parse_name("2026-10-07_lease_anna-de-vries_huur-kerkstraat.pdf") == (
        "2026-10-07", "lease", "anna-de-vries", "huur-kerkstraat", "pdf"
    )  # fmt: skip
    assert parse_name("2026-10-07_hologram_x_y.pdf") is None
    assert parse_name("factuur.pdf") is None


def test_payslip_and_bank_statement_text_is_finance_text() -> None:
    assert looks_like_finance_text("Salarisspecificatie mei 2026. Brutoloon 3.100,00. Loonheffing 312,00.")
    assert looks_like_finance_text("Rekeningafschrift nr. 14. Beginsaldo 1.200,00, eindsaldo 950,00.")
    assert looks_like_finance_text("Werkgeversverklaring: mevrouw is sinds 2021 in vaste dienst.")


def test_a_lease_with_payment_details_is_not_finance_text() -> None:
    lease = "Huurovereenkomst Singel 5. De huur van EUR 1.250 wordt maandelijks voldaan op IBAN NL00BANK0123456789."
    assert not looks_like_finance_text(lease)

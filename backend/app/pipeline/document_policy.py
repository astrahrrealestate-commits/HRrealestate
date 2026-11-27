"""#9 Document Filing policy (pure): what to skip, the file naming rule v1, the Drive folder, the confidence gate.

Naming rule v1: `{YYYY-MM-DD}_{doc_type}_{party}_{title}.{ext}`. The date is the document's own date, else the day
the message arrived in the company's timezone. Party and title are ASCII slugs, so a name is always one safe path
segment (no separators, no `..`), whatever the model or the sender wrote.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.contracts import DocType, DocumentClassification
from app.db.enums import DocumentStatus

FILE_THRESHOLD = 0.80
MIN_IMAGE_BYTES = 20_000  # smaller images are logos, signatures and tracking pixels
ROOT_FOLDER = "EstateOS"
_SKIP_MIME_PREFIXES = (
    "text/html",
    "text/calendar",
    "text/directory",
    "text/vcard",
    "text/x-vcard",
    "application/pgp-signature",
    "application/pkcs7-signature",
)
_SKIP_SUFFIXES = (".ics", ".vcf", ".p7s", ".asc")
_MIME_EXT = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/heic": "heic", "image/webp": "webp",
    "image/tiff": "tif", "application/msword": "doc", "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}  # fmt: skip
_SAFE_EXT = frozenset({"pdf", "jpg", "jpeg", "png", "heic", "webp", "tif", "tiff", "doc", "docx", "xls", "xlsx", "odt",
                       "ods", "txt", "csv", "eml"})  # fmt: skip


@dataclass(frozen=True)
class FileMeta:
    filename: str | None
    mime_type: str
    size_bytes: int
    sent_at: datetime


def should_skip(meta: FileMeta) -> bool:
    name = (meta.filename or "").lower()
    if meta.size_bytes <= 0:
        return True
    if meta.mime_type.startswith("image/") and meta.size_bytes < MIN_IMAGE_BYTES:
        return True
    if meta.mime_type == "text/plain" and not meta.filename:
        return True
    return meta.mime_type.startswith(_SKIP_MIME_PREFIXES) or name.endswith(_SKIP_SUFFIXES)


_ID_NAME = re.compile(r"passport|paspoort|identiteit|id[-_ ]?(kaart|card)|rijbewijs|driver.?licen|\bbsn\b", re.I)


def looks_like_id(meta: FileMeta) -> bool:
    """A file name that says it is an identity document: never read its contents (ADR 0007)."""
    return bool(meta.filename and _ID_NAME.search(meta.filename))


_MRZ = re.compile(r"^[A-Z0-9<]{28,44}$", re.MULTILINE)
_ID_WORDS = re.compile(
    r"paspoort|passport|identiteitskaart|identity card|rijbewijs|driving licen[cs]e|verblijfsdocument|"
    r"residence permit|personalausweis|reisepass",
    re.IGNORECASE,
)
_ID_FIELDS = re.compile(
    r"geboortedatum|date of birth|nationaliteit|nationality|documentnummer|document no|geldig tot|date of expiry|"
    r"\b4[abcd]\.\s|\bBSN\b|burgerservicenummer",
    re.IGNORECASE,
)
_BSN = re.compile(r"(?:burgerservicenummer|\bBSN\b)\s*:?\s*\d{8,9}\b", re.IGNORECASE)


def looks_like_id_text(text: str) -> bool:
    """Text that reads like a passport, ID card, driving licence or residence permit, or carries a BSN: a passport
    machine-readable line, or a document word with an identity field. File names prove nothing (ADR 0007)."""
    head = text[:20_000]
    if any("<<" in line for line in _MRZ.findall(head)) or _BSN.search(head):
        return True
    return bool(_ID_WORDS.search(head) and _ID_FIELDS.search(head))


_FINANCE = re.compile(
    r"loonstrook|salarisstrook|salarisspecificatie|loonspecificatie|loonheffing|brutoloon|nettoloon|payslip|"
    r"pay slip|rekeningafschrift|bankafschrift|bank statement|beginsaldo|eindsaldo|jaaropgaaf|werkgeversverklaring",
    re.IGNORECASE,
)


def looks_like_finance_text(text: str) -> bool:
    """Text that reads like a payslip, employer statement or bank statement: a tenant's income papers, never draft
    context (M13, BRIXX documents). Words, not names: these papers often carry a neutral title."""
    return bool(_FINANCE.search(text[:20_000]))


def slug(text: str, limit: int = 40) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    cut = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:limit].strip("-")
    return cut or "unknown"


def _extension(meta: FileMeta) -> str:
    """The MIME type wins when known (`factuur.pdf.exe` sent as PDF is `.pdf`); else an allowlisted name suffix."""
    if meta.mime_type in _MIME_EXT:
        return _MIME_EXT[meta.mime_type]
    if meta.filename and "." in meta.filename:
        ext = meta.filename.rsplit(".", 1)[1].lower()
        if ext in _SAFE_EXT:
            return ext
    return "bin"


def _day(cls: DocumentClassification, meta: FileMeta, tz: str) -> date:
    return cls.document_date or meta.sent_at.astimezone(ZoneInfo(tz)).date()


def document_day(cls: DocumentClassification, meta: FileMeta, tz: str) -> date:
    """The day that dates a document: its own date, else the day its message arrived in the company's timezone."""
    return _day(cls, meta, tz)


def file_name(cls: DocumentClassification, meta: FileMeta, party: str, tz: str) -> str:
    day = _day(cls, meta, tz).isoformat()
    return f"{day}_{cls.doc_type.value}_{slug(party)}_{slug(cls.title)}.{_extension(meta)}"


def folder_path(cls: DocumentClassification, meta: FileMeta, tz: str) -> tuple[str, ...]:
    return (ROOT_FOLDER, cls.doc_type.value, str(_day(cls, meta, tz).year))


def filing_status(cls: DocumentClassification) -> DocumentStatus:
    return DocumentStatus.filed if cls.confidence >= FILE_THRESHOLD else DocumentStatus.review


def _kinds() -> str:
    return "|".join(sorted((t.value for t in DocType), key=len, reverse=True))  # id_document has an underscore


_NAME = re.compile(rf"^(\d{{4}}-\d{{2}}-\d{{2}})_({_kinds()})_([^_]+)_(.+)\.([a-z0-9]+)$")


def parse_name(name: str) -> tuple[str, str, str, str, str] | None:
    """`(date, kind, party, title, ext)` of a rule-v1/v2 file name, or None when it does not follow the rule."""
    found = _NAME.match(name)
    if found is None:
        return None
    day, kind, party, title, ext = found.groups()
    return day, kind, party, title, ext


def name_date(name: str) -> date | None:
    """The date at the start of a rule-v1 file name (the stored `documents.file_name`), if any."""
    try:
        return date.fromisoformat(name[:10])
    except ValueError:
        return None

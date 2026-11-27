"""Document text extraction (M10, ADR 0007): bytes in, text out. No network, no model; scans report `needs_ocr`.

Limits keep a hostile or huge file from costing real money or memory: over a limit is `skipped` (the document is still
filed from metadata), a file that cannot be parsed is `failed`. Neither is retried.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from html import unescape
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.logging import get_logger
from app.db.enums import ExtractionStatus

log = get_logger(__name__)

PAGE_BREAK = "\f"  # a PDF text starts with one and has one before each page: chunks know their page
MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 40
MAX_CHARS = 200_000
MIN_CHARS_PER_PAGE = 40  # fewer than this on average: the PDF is a scan, not text
_MAX_XML_BYTES = 20 * 1024 * 1024  # an unzipped word/document.xml above this is a zip bomb
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PLAIN = ("text/plain", "text/csv", "message/rfc822")
_IMAGES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/tiff")
_GENERIC_MIME = frozenset({"", "application/octet-stream", "binary/octet-stream", "application/x-unknown"})
_EXT_MIME = {
    ".pdf": "application/pdf",
    ".docx": _DOCX,
    ".xlsx": _XLSX,
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".eml": "message/rfc822",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heic",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


def canonical_mime(mime_type: str, filename: str | None) -> str:
    """Resolve generic `application/octet-stream` attachments from their extension; explicit MIME wins."""
    mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if mime in _GENERIC_MIME and filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[1].strip().lower()
        return _EXT_MIME.get(ext, mime or "application/octet-stream")
    return mime or "application/octet-stream"


@dataclass(frozen=True)
class Extraction:
    status: ExtractionStatus
    text: str | None
    page_count: int | None
    extractor: str
    needs_ocr: bool = False
    note: str | None = None


class TextExtractor(Protocol):
    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction: ...


def _skipped(extractor: str, note: str, *, needs_ocr: bool = False, pages: int | None = None) -> Extraction:
    return Extraction(ExtractionStatus.skipped, None, pages, extractor, needs_ocr=needs_ocr, note=note)


def _clean(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text.replace("\x00", ""))).strip()


def _pdf(data: bytes) -> Extraction:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _skipped("pypdf", "encrypted")
        pages = len(reader.pages)
        if pages > MAX_PAGES:
            return _skipped("pypdf", f"over {MAX_PAGES} pages", pages=pages)
        text = PAGE_BREAK + PAGE_BREAK.join(_clean(page.extract_text() or "") for page in reader.pages)
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as exc:
        return Extraction(ExtractionStatus.failed, None, None, "pypdf", note=f"{type(exc).__name__}"[:200])
    if len(text.replace(PAGE_BREAK, "").strip()) < MIN_CHARS_PER_PAGE * max(pages, 1):
        return _skipped("pypdf", "scanned pdf, needs vision", needs_ocr=True, pages=pages)
    return Extraction(ExtractionStatus.done, text[:MAX_CHARS], pages, "pypdf")


def _docx(data: bytes) -> Extraction:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > _MAX_XML_BYTES:
                return _skipped("docx", "document too large")
            xml = archive.read(info).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError, OSError):
        return Extraction(ExtractionStatus.failed, None, None, "docx", note="unreadable docx")
    paragraphs = (re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p) for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S))
    text = _clean("\n".join(unescape("".join(runs)) for runs in paragraphs))
    return Extraction(ExtractionStatus.done, text[:MAX_CHARS], None, "docx") if text else _skipped("docx", "empty")


def _xlsx_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    info = archive.getinfo("xl/sharedStrings.xml")
    if info.file_size > _MAX_XML_BYTES:
        return []
    xml = archive.read(info).decode("utf-8", errors="replace")
    return [
        unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)))
        for si in re.findall(r"<si\b[^>]*>(.*?)</si>", xml, re.S)
    ]


def _xlsx_rows(xml: str, shared: list[str]) -> list[str]:
    lines: list[str] = []
    for row in re.findall(r"<row\b[^>]*>(.*?)</row>", xml, re.S):
        cells: list[str] = []
        for attrs, body in re.findall(r"<c\b([^>]*)>(.*?)</c>", row, re.S):
            t_match = re.search(r'\bt="([^"]*)"', attrs)
            ctype = t_match.group(1) if t_match else ""
            if ctype == "inlineStr":
                text = unescape("".join(re.findall(r"<t[^>]*>([^<]*)</t>", body))).strip()
            else:
                v_match = re.search(r"<v[^>]*>([^<]*)</v>", body)
                val = unescape(v_match.group(1)).strip() if v_match else ""
                text = shared[int(val)].strip() if ctype == "s" and val.isdigit() and int(val) < len(shared) else val
            if text:
                cells.append(text)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _xlsx(data: bytes) -> Extraction:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            sheets = sorted(n for n in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
            if not sheets:
                return _skipped("xlsx", "no worksheets")
            shared = _xlsx_strings(archive)
            lines: list[str] = []
            for sheet in sheets:
                info = archive.getinfo(sheet)
                if info.file_size > _MAX_XML_BYTES:
                    return _skipped("xlsx", "sheet too large")
                lines.extend(_xlsx_rows(archive.read(info).decode("utf-8", errors="replace"), shared))
    except (zipfile.BadZipFile, KeyError, OSError, ValueError):
        return Extraction(ExtractionStatus.failed, None, None, "xlsx", note="unreadable xlsx")
    text = _clean("\n".join(lines))
    return Extraction(ExtractionStatus.done, text[:MAX_CHARS], None, "xlsx") if text else _skipped("xlsx", "empty")


def _plain(data: bytes) -> Extraction:
    text = _clean(data.decode("utf-8", errors="replace"))
    return Extraction(ExtractionStatus.done, text[:MAX_CHARS], None, "plain") if text else _skipped("plain", "empty")


class LocalExtractor:
    """pypdf for text PDFs, stdlib for docx/xlsx and plain text; images are handed to vision (`needs_ocr`)."""

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        if len(data) > MAX_BYTES:
            return _skipped("local", "file too large")
        kind = canonical_mime(mime_type, filename)
        if kind == "application/pdf":
            return _pdf(data)
        if kind == _DOCX:
            return _docx(data)
        if kind == _XLSX:
            return _xlsx(data)
        if kind in _PLAIN:
            return _plain(data)
        if kind in _IMAGES:
            return _skipped("local", "image, needs vision", needs_ocr=True)
        return _skipped("local", f"unsupported type {kind}")


class FakeExtractor:
    """Tests and the simulator: UTF-8 text files are their own text; a `scan` marker file needs vision."""

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        if data.startswith(b"SCAN"):
            return _skipped("fake", "scan", needs_ocr=True)
        raw = data.decode("utf-8", errors="replace")
        text = _clean(raw)
        if not text:
            return _skipped("fake", "empty")
        text = PAGE_BREAK + text if raw.startswith(PAGE_BREAK) else text  # a paged fake text keeps its page marks
        return Extraction(ExtractionStatus.done, text[:MAX_CHARS], 1, "fake")

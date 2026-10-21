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

MAX_BYTES = 15 * 1024 * 1024
MAX_PAGES = 40
MAX_CHARS = 200_000
MIN_CHARS_PER_PAGE = 40  # fewer than this on average: the PDF is a scan, not text
_MAX_XML_BYTES = 20 * 1024 * 1024  # an unzipped word/document.xml above this is a zip bomb
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PLAIN = ("text/plain", "text/csv", "message/rfc822")
_IMAGES = ("image/jpeg", "image/png", "image/webp", "image/heic", "image/tiff")


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
        text = _clean("\n\n".join(page.extract_text() or "" for page in reader.pages))
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as exc:
        return Extraction(ExtractionStatus.failed, None, None, "pypdf", note=f"{type(exc).__name__}"[:200])
    if len(text) < MIN_CHARS_PER_PAGE * max(pages, 1):
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


def _plain(data: bytes) -> Extraction:
    text = _clean(data.decode("utf-8", errors="replace"))
    return Extraction(ExtractionStatus.done, text[:MAX_CHARS], None, "plain") if text else _skipped("plain", "empty")


class LocalExtractor:
    """pypdf for text PDFs, stdlib for docx and plain text; images are handed to vision (`needs_ocr`)."""

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        if len(data) > MAX_BYTES:
            return _skipped("local", "file too large")
        if mime_type == "application/pdf":
            return _pdf(data)
        if mime_type == _DOCX:
            return _docx(data)
        if mime_type in _PLAIN:
            return _plain(data)
        if mime_type in _IMAGES:
            return _skipped("local", "image, needs vision", needs_ocr=True)
        return _skipped("local", f"unsupported type {mime_type}")


class FakeExtractor:
    """Tests and the simulator: UTF-8 text files are their own text; a `scan` marker file needs vision."""

    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        if data.startswith(b"SCAN"):
            return _skipped("fake", "scan", needs_ocr=True)
        text = _clean(data.decode("utf-8", errors="replace"))
        if not text:
            return _skipped("fake", "empty")
        return Extraction(ExtractionStatus.done, text[:MAX_CHARS], 1, "fake")

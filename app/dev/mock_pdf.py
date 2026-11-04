"""Smallest valid text PDF (Helvetica, A4, 50 lines a page) for the mock documents of the agent tour.

The text sits in the page content stream, so the pipeline's text extractor reads it back like any digital PDF.
"""

from collections.abc import Sequence

LINES_PER_PAGE = 50
_FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _escape(line: str) -> bytes:
    cleaned = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return cleaned.encode("cp1252", errors="replace")


def _content(lines: Sequence[str]) -> bytes:
    body = b"BT /F1 11 Tf 14 TL 50 800 Td\n" + b"".join(b"(" + _escape(line) + b") Tj T*\n" for line in lines) + b"ET"
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(body), body)


def text_pdf(lines: Sequence[str]) -> bytes:
    """One page per `LINES_PER_PAGE` lines. Object numbers: 1 catalog, 2 pages, 3 font, then (page, content) pairs."""
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)]
    kids = [4 + 2 * n for n in range(len(pages))]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{k} 0 R" for k in kids).encode(), len(pages)),
        _FONT,
    ]
    for kid, page in zip(kids, pages, strict=True):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % (kid + 1)
        )
        objects.append(_content(page))
    return _serialise(objects)


def _serialise(objects: Sequence[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)

"""Split a document's text into searchable chunks (ADR 0008). Pure.

Pages come from the extractor (a form feed starts each page; a text with none is unpaged). A chunk is about 1,500
characters, starts at a heading when there is one, overlaps its predecessor by about 200 characters so a clause cut
at the boundary is whole in one of them, and remembers its page and the heading it sits under.
"""

import re
from dataclasses import dataclass

TARGET = 1500
OVERLAP = 200
MIN_CHUNK = 300
PAGE_BREAK = "\f"
_NUMBERED = re.compile(
    r"^(?:(?:artikel|article|hoofdstuk|chapter|bijlage|appendix)\s+\d+\S*.*|\d+(?:\.\d+)*[.)]?\s+\S.*)$", re.I
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    text: str
    page: int | None
    heading: str | None


@dataclass(frozen=True)
class _Unit:
    text: str
    page: int | None
    heading: str | None
    is_heading: bool = False


def is_heading(line: str) -> bool:
    """A short line that names a section: ALL CAPS, or numbered/`Artikel 4` style without sentence punctuation."""
    s = line.strip()
    if not 3 <= len(s) <= 80 or s.endswith((".", ",", ";", ":")):
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        return True
    return bool(_NUMBERED.match(s))


def _split_long(text: str) -> list[str]:
    """A paragraph over the target is cut at sentence ends, then at spaces."""
    if len(text) <= TARGET:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > TARGET:
            cut = sentence.rfind(" ", 0, TARGET)
            cut = cut if cut > 0 else TARGET
            parts.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if current and len(current) + len(sentence) + 1 > TARGET:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return [p for p in parts if p]


def _flush(units: list[_Unit], block: list[str], page: int | None, heading: str | None) -> None:
    body = "\n".join(block).strip()
    block.clear()
    units.extend(_Unit(part, page, heading) for part in _split_long(body) if part)


def _units(text: str) -> list[_Unit]:
    paged = PAGE_BREAK in text
    pages = text.split(PAGE_BREAK)
    if text.startswith(PAGE_BREAK):
        pages = pages[1:]  # a leading break marks a paged text: the part before it is empty
    units: list[_Unit] = []
    heading: str | None = None
    for number, page in enumerate(pages, start=1):
        shown = number if paged else None
        block: list[str] = []
        for line in page.split("\n"):
            if not line.strip():
                _flush(units, block, shown, heading)
            elif is_heading(line):
                _flush(units, block, shown, heading)
                heading = line.strip()[:200]
                units.append(_Unit(heading, shown, heading, is_heading=True))
            else:
                block.append(line.strip())
        _flush(units, block, shown, heading)
    return units


def _tail(text: str) -> str:
    """The last ~OVERLAP characters of a chunk, from a word boundary."""
    if len(text) <= OVERLAP:
        return ""
    cut = text.find(" ", len(text) - OVERLAP)
    return text[cut + 1 :] if cut != -1 else ""


def chunk_document(text: str) -> list[Chunk]:
    """Heading- and page-aware chunks with overlap, in reading order. Empty text gives no chunks."""
    chunks: list[Chunk] = []
    current: list[str] = []
    first: _Unit | None = None

    def emit() -> None:
        nonlocal current, first
        body = "\n".join(current).strip()
        if body and first is not None:
            chunks.append(Chunk(body, first.page, first.heading))
        current, first = ([_tail(body)] if _tail(body) else []), None

    for unit in _units(text):
        size = sum(len(t) + 1 for t in current)
        if current and first is not None and size >= MIN_CHUNK and (unit.is_heading or size + len(unit.text) > TARGET):
            emit()
        if first is None:
            first = unit
        current.append(unit.text)
    if first is not None and "\n".join(current).strip():
        emit()
    if (
        len(chunks) > 1
        and len(chunks[-1].text) < MIN_CHUNK
        and len(chunks[-2].text) + len(chunks[-1].text) <= TARGET * 1.3
    ):
        last = chunks.pop()
        chunks[-1] = Chunk(f"{chunks[-1].text}\n{last.text}", chunks[-1].page, chunks[-1].heading)
    return chunks

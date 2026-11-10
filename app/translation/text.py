"""Turn a message into sentence-sized segments for the model and stitch the English back together.

The Marian model drops everything after the first sentence of a long input, so each sentence is its own segment.
Lines, blank lines and segments without letters (phone numbers, amounts, references) are kept as written.
Work per request is bounded twice: by characters and by segment count (a text of one-letter sentences is cheap in
characters but expensive for the model).
"""

import re

from app.core.errors import TranslationUnavailableError
from app.translation.ports import Translator

MAX_SEGMENT_CHARS = 400
MAX_TEXT_CHARS = 8000  # bounds CPU per request; the rest of a long thread is still readable in Dutch
MAX_SEGMENTS = 80  # about the most sentences a real 8000-character message has

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")
_HAS_LETTER = re.compile(r"[A-Za-zÀ-ÿ]")
# A Dutch abbreviation ends in a full stop without ending the sentence ("Dhr. Jansen", "bijv. de", "t.a.v. X").
_ABBREVIATION = re.compile(
    r"(?:^|\s)(?:dhr|mevr|mw|mr|drs|ir|ing|nr|bijv|ca|etc|enz|blz|vs|incl|excl|tel|ma|di|wo|do|vr|za|zo)\.$"
    r"|(?:\b\w\.){2,}$",
    re.IGNORECASE,
)


def _split_long(sentence: str) -> list[str]:
    parts: list[str] = []
    current = ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > MAX_SEGMENT_CHARS:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return [*parts, current] if current else parts


def _sentences(line: str) -> list[str]:
    merged: list[str] = []
    carry = ""
    for piece in _SENTENCE_END.split(line.strip()):
        piece = f"{carry} {piece}".strip()
        carry = piece if _ABBREVIATION.search(piece) else ""
        if not carry:
            merged.append(piece)
    if carry:
        merged.append(carry)
    out: list[str] = []
    for sentence in merged:
        out.extend(_split_long(sentence) if len(sentence) > MAX_SEGMENT_CHARS else [sentence])
    return out


def _capped(lines: list[list[str]]) -> tuple[list[list[str]], bool]:
    """The lines with at most MAX_SEGMENTS sentences that have letters; anything after is dropped."""
    kept: list[list[str]] = []
    counted = 0
    for line in lines:
        keep: list[str] = []
        for sentence in line:
            if _HAS_LETTER.search(sentence):
                if counted == MAX_SEGMENTS:
                    return [*kept, keep], True
                counted += 1
            keep.append(sentence)
        kept.append(keep)
    return kept, False


def translate_text(translator: Translator, text: str) -> str:
    """The English for `text`; one model batch for the whole message."""
    clipped = text[:MAX_TEXT_CHARS]
    lines, cut = _capped([_sentences(line) if line.strip() else [] for line in clipped.split("\n")])
    todo = [s for line in lines for s in line if _HAS_LETTER.search(s)]
    english = translator.translate(todo) if todo else []
    if len(english) != len(todo):
        raise TranslationUnavailableError(f"translator returned {len(english)} segments for {len(todo)}")
    done = iter(english)
    rebuilt = [" ".join(next(done) if _HAS_LETTER.search(s) else s for s in line) for line in lines]
    result = "\n".join(rebuilt).strip()
    return f"{result}…" if result and (cut or len(text) > MAX_TEXT_CHARS) else result

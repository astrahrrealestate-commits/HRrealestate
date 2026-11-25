"""Quoted history in a mail body: where the new part ends and which earlier messages are quoted below it (M13).

Everything here is text the sender controls: a quoted "Harjot wrote" is context and a reason not to draft again, never
proof that he wrote it and never an approval.
"""

import re
from dataclasses import dataclass

from app.channels.gmail.forward import FORWARD_MARKERS

_PREFIX = r"^[ \t>]{0,40}"
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
# "On … <a@b> wrote:" and its Dutch and German forms, which mail-parser-reply misses (Gmail and Apple Mail in Dutch).
# Clients wrap the line, so it may span three lines; lengths are bounded, because the text is hostile input.
_LINE = r"[^\n]{0,300}"
_ATTRIBUTION = re.compile(
    _PREFIX + r"(?:On|Op|Am)\b(?=" + _LINE + r"\d)(?:" + _LINE + r"\n){0,2}?" + _LINE + r"(?:\bwrote[ \t]{0,3}:"
    r"|\b(?:schreef|schrieb)\b[^\n:]{0,200}(?:mailto:)?[^\n:]{0,200}:|\bhet volgende geschreven[ \t]{0,3}:)[ \t]{0,5}$",
    re.IGNORECASE | re.MULTILINE,
)
_TIME = re.compile(
    r"\b\d{1,2}[:.]\d{2}\b"
)  # an attribution names an address or a time; a sentence about a date does not
_ORIGINAL = re.compile(_PREFIX + r"-{3,}\s*(?:Original Message|Oorspronkelijk bericht|Ursprüngliche Nachricht)\s*-{3,}",
                       re.IGNORECASE | re.MULTILINE)  # fmt: skip
# Outlook: a From line with a Sent/Date line right below it.
_OUTLOOK = re.compile(
    _PREFIX + r"(?:From|Van|Von)[ \t]*:" + _LINE + r"\n(?:" + _LINE + r"\n){0,2}?"
    r"[ \t>]{0,20}(?:Sent|Date|Verzonden|Datum|Gesendet)[ \t]*:" + _LINE + r"$",
    re.IGNORECASE | re.MULTILINE,
)
_HEADER = re.compile(
    r"^\s*(?:From|Van|Von|Sent|Date|Verzonden|Datum|Gesendet|To|Aan|An|Cc|Subject|Onderwerp|Betreff)\s*:", re.IGNORECASE
)
_RULE = re.compile(r"^\s*_{5,}\s*$")
_FORWARD_HEADER_CHARS = 1200  # the header block of a forwarded mail sits right under its marker


@dataclass(frozen=True)
class QuotedMessage:
    author: str | None  # the address in the attribution line, lower-cased; unverified
    text: str


def _boundaries(text: str) -> list[re.Match[str]]:
    """Every place an earlier message starts, in order. A first forward marker is not one: the forwarded mail is the
    message itself, and the header block under the marker belongs to it."""
    forwards = list(FORWARD_MARKERS.finditer(text))
    header = range(0)
    if forwards:
        start = forwards[0].end()
        blank = text.find("\n\n", start, start + _FORWARD_HEADER_CHARS)
        header = range(start, blank if blank >= 0 else start + _FORWARD_HEADER_CHARS)
    attributions = [m for m in _ATTRIBUTION.finditer(text) if _EMAIL.search(m.group(0)) or _TIME.search(m.group(0))]
    found = [*attributions, *_ORIGINAL.finditer(text), *_OUTLOOK.finditer(text), *forwards[1:]]
    ordered = sorted((m for m in found if m.start() not in header), key=lambda m: m.start())
    kept: list[re.Match[str]] = []
    for m in ordered:
        if kept and m.start() < kept[-1].end() + 4:  # an Outlook header right under "Original Message" is the same one
            continue
        kept.append(m)
    return kept


def split_quoted(text: str) -> tuple[str, str]:
    """(new part, quoted part). The quoted part is empty when the mail quotes nothing."""
    marks = _boundaries(text)
    if not marks:
        return text, ""
    cut = marks[0].start()
    new = text[:cut].rstrip()
    lines = new.split("\n")
    if _RULE.match(lines[-1]):  # Outlook draws a rule above the quoted header
        new = "\n".join(lines[:-1]).rstrip()
    return new, text[cut:].strip()


def _clean(body: str) -> str:
    lines = [re.sub(r"^[ \t>﻿]+", "", line).rstrip() for line in body.split("\n")]
    while lines and (not lines[0] or _HEADER.match(lines[0])):
        lines.pop(0)
    return "\n".join(lines).strip()


def _author(text: str, mark: re.Match[str], until: int) -> str | None:
    """The address in the attribution, or in the From line just under an "Original Message" marker."""
    found = _EMAIL.search(mark.group(0))
    if found is None:
        for line in text[mark.end() : until].split("\n")[:6]:
            if re.match(_PREFIX + r"(?:From|Van|Von)\s*:", line, re.IGNORECASE):
                found = _EMAIL.search(line)
                break
    return found.group(0).lower() if found else None


def quoted_messages(text: str) -> list[QuotedMessage]:
    """The messages quoted below the new part, as the mail shows them (usually newest first)."""
    marks = _boundaries(text)
    out: list[QuotedMessage] = []
    for i, mark in enumerate(marks):
        until = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = _clean(text[mark.end() : until])
        if body:
            out.append(QuotedMessage(_author(text, mark, until), body))
    return out


def quoted_owner_reply(text: str, owner: frozenset[str]) -> bool:
    """Whether the quoted part holds a message written from one of the owner's addresses (unverified)."""
    return any(m.author in owner for m in quoted_messages(text))

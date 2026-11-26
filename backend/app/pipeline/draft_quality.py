"""Harjot's drafting standard in code (M13 T9): a draft that only acknowledges or promises to come back is not offered.

A sentence counts as empty when it is a greeting, a sign-off, a thanks, a receipt or a promise to get back, and holds
no question, figure or decision (restating the topic does not count). A draft with nothing but empty sentences is
generic.
"""

import re
from collections.abc import Sequence

GENERIC_PHRASES: tuple[str, ...] = (
    # thanks and receipt
    r"\b(hartelijk |heel erg |veel )?(dank|bedankt)\b",
    r"\bthank(s| you)\b",
    r"\bin goede orde ontvangen\b",
    r"\b(we|wij|ik) (hebben|heb) (uw|je|jouw) .{0,40}ontvangen\b",
    r"\b(uw|je|jouw) .{0,40}is (goed )?ontvangen\b",
    r"\b(we|i) (have )?received (it|your)\b",
    # a promise to come back, look into it or get in touch
    r"\b(we|wij|ik) (nemen|neem) .{0,40}in behandeling\b",
    r"\bkomen? .{0,30}(zo snel|zo spoedig|spoedig|binnenkort|z\.s\.m\.)",
    r"\b(nemen?|neem) .{0,30}contact .{0,20}op\b",
    r"\b(op terug|bij u terug|bij je terug|laat .{0,20}weten)\b",
    r"\b(kijk|kijken|bekijk|bekijken) (er(naar)?|dit|het)\b",
    r"\bzo snel (als|mogelijk)\b",
    r"\b(get|come) back to you\b",
    r"\b(will )?follow up\b",
    r"\blooking into (this|it)\b",
    r"\bas soon as (possible|i can|we can)\b",
    r"\b(we|i) will (be in touch|reply|respond|let you know)\b",
    r"\breaching out\b",
)
_EMPTY = re.compile("|".join(GENERIC_PHRASES), re.IGNORECASE)
_GREETING = re.compile(
    r"^(beste|geachte|hallo|hoi|dag|goedemorgen|goedemiddag|dear|hi|hello)\b[^.!?\n]{0,60}[,!]?\s*$", re.IGNORECASE
)
_SIGN_OFF = re.compile(
    r"^(met )?(vriendelijke|hartelijke) groet(en)?|^groet(en|jes)?\b|^(best|kind|warm) regards|^regards\b|^harjot\b",
    re.IGNORECASE,
)
_SUBSTANCE = re.compile(r"\?|\d")
# A decision, an instruction or a concrete next step: what turns a thanks into an answer.
_DECISION = re.compile(
    r"\b(akkoord|accepteren|accepteert|weigeren|stuur|sturen|stuurt|betalen|betaalt|storten|vergoeden|vervangen|"
    r"repareren|herstellen|bieden|bied|ingepland|plannen|afspraak|langs|komt kijken|verzoeken? u|vragen u|graag "
    r"ontvangen|neem(t)? .{0,20}mee|zet .{0,20}uit|draai .{0,20}dicht|agree|decline|send|pay|replace|repair|offer|"
    r"schedule|appointment|please (send|provide|confirm))\b",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> list[str]:
    out: list[str] = []
    for part in _SENTENCE.split(text):
        clean = part.strip(" \t-•*")
        if clean and not _GREETING.match(clean) and not _SIGN_OFF.match(clean):
            out.append(clean)
    return out


def _empty(sentence: str) -> bool:
    """A thanks, receipt or promise to come back, however long, with no question, figure or decision in it."""
    return bool(_EMPTY.search(sentence)) and not _SUBSTANCE.search(sentence) and not _DECISION.search(sentence)


def is_generic(text: str) -> bool:
    """True when the draft says nothing but thanks, receipt or a promise to come back."""
    return all(_empty(s) for s in _sentences(text))


def usable_variants(variants: Sequence[str]) -> list[str]:
    return [v for v in variants if not is_generic(v)]

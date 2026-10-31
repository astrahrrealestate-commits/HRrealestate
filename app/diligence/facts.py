"""Shared reading of the verified reads: which documents count, which claim is the reference for a fact, and how a
claim's value is normalised for comparison."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.contracts.diligence import FIELD_KIND, DDClaim, DDDocRead, DDField, ValueKind
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_LEASEHOLD = ("erfpacht", "leasehold", "ground lease")
_OWNED = ("eigendom", "freehold", "owned", "appartementsrecht", "apartment_right")
_ABSENT = ("absent", "afwezig", "niet aanwezig", "geen asbest", "none")
_PRESENT = ("present", "aanwezig", "found", "aangetroffen")

Value = Decimal | date | str


@dataclass(frozen=True)
class ReadableDoc:
    document_id: UUID
    title: str
    read: DDDocRead
    authority: int


def is_readable(framework: Framework, doc: DocInput) -> bool:
    return doc.read is not None and doc.read.confidence >= framework.thresholds.min_confidence


def readable_docs(framework: Framework, docs: list[DocInput]) -> list[ReadableDoc]:
    """Documents read with enough confidence, most authoritative first; order does not depend on the input order."""
    out = [
        ReadableDoc(d.document_id, d.read.title, d.read, framework.authority[d.read.doc_kind])
        for d in docs
        if d.read is not None and is_readable(framework, d)
    ]
    return sorted(out, key=lambda r: (-r.authority, r.read.doc_kind.value, str(r.document_id)))


def normalise_text(field: DDField, text: str) -> str:
    low = " ".join(text.casefold().split())
    if field is DDField.ownership_type:
        if any(w in low for w in _LEASEHOLD):
            return "leasehold"
        return "freehold" if any(w in low for w in _OWNED) else low
    if field is DDField.asbestos:
        if any(w in low for w in _ABSENT):
            return "absent"
        return "present" if any(w in low for w in _PRESENT) else low
    if field is DDField.energy_label:
        return low.replace(" ", "").upper()
    if field is DDField.address:
        return _NON_ALNUM.sub(" ", low).strip()
    return low


def claim_value(claim: DDClaim) -> Value:
    kind = FIELD_KIND[claim.field]
    if kind is ValueKind.number and claim.number is not None:
        return claim.number
    if kind is ValueKind.day and claim.day is not None:
        return claim.day
    return normalise_text(claim.field, claim.text or "")


def claims_of(docs: list[ReadableDoc], field: DDField) -> list[tuple[ReadableDoc, DDClaim]]:
    return [(d, c) for d in docs for c in d.read.claims if c.field is field]


def reference_claim(docs: list[ReadableDoc], field: DDField) -> tuple[ReadableDoc, DDClaim] | None:
    """The claim to trust for a fact: from the most authoritative document that states it."""
    found = claims_of(docs, field)
    return found[0] if found else None


def number_of(docs: list[ReadableDoc], field: DDField) -> Decimal | None:
    ref = reference_claim(docs, field)
    return ref[1].number if ref else None


def text_of(docs: list[ReadableDoc], field: DDField) -> str | None:
    ref = reference_claim(docs, field)
    return normalise_text(field, ref[1].text or "") if ref else None


def day_of(docs: list[ReadableDoc], field: DDField) -> date | None:
    ref = reference_claim(docs, field)
    return ref[1].day if ref else None

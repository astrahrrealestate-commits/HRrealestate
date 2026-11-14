"""Mismatches: the same fact stated differently across documents. The most authoritative statement is the reference."""

from datetime import date
from decimal import Decimal

from app.contracts.diligence import DDClaim, DDDocKind, DDField
from app.contracts.diligence_report import DDSeverity, Mismatch, MismatchKind, MismatchSide
from app.diligence.facts import ReadableDoc, Value, claim_value, claims_of, readable_docs
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput

_PERCENT = Decimal(100)
_DECISIVE = frozenset({DDField.ground_lease_end, DDField.ownership_type, DDField.asbestos, DDField.energy_label})


def _show(value: Value) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _agree(fw: Framework, field: DDField, a: Value, b: Value) -> bool:
    if isinstance(a, Decimal) and isinstance(b, Decimal):
        return abs(a - b) <= fw.tolerance(field) * max(abs(a), abs(b))
    return a == b


def _difference(ref: Value, other: Value) -> str:
    if isinstance(ref, Decimal) and isinstance(other, Decimal):
        pct = f" ({(other - ref) / ref * _PERCENT:+.1f}%)" if ref else ""
        return f"{_show(other)} vs {_show(ref)}{pct}"
    if isinstance(ref, date) and isinstance(other, date):
        return f"{other} vs {ref} ({(other - ref).days:+d} days)"
    return f"'{other}' vs '{ref}'"


def _side(doc: ReadableDoc, claim: DDClaim) -> MismatchSide:
    return MismatchSide(
        document_id=doc.document_id, title=doc.title, doc_kind=doc.read.doc_kind,
        value=_show(claim_value(claim)), quote=claim.quote,
    )  # fmt: skip


def _classify(field: DDField, ref: ReadableDoc, other: ReadableDoc) -> tuple[MismatchKind, DDSeverity]:
    marketing = (
        other.read.doc_kind is DDDocKind.brochure
        and other.document_id != ref.document_id
        and ref.authority > other.authority
    )
    if not marketing:
        # two official sources disagreeing on a fact that decides the deal is not a footnote
        return MismatchKind.inconsistent, DDSeverity.high if field in _DECISIVE else DDSeverity.medium
    # asking price and agreed price legitimately differ, so a price gap is worth a look, not an alarm
    return MismatchKind.marketing_vs_legal, DDSeverity.medium if field is DDField.price else DDSeverity.high


def find_mismatches(fw: Framework, docs: list[DocInput]) -> list[Mismatch]:
    readable = readable_docs(fw, docs)
    found: list[Mismatch] = []
    for field in DDField:
        claims = claims_of(readable, field)
        if len(claims) < 2:
            continue
        ref_doc, ref_claim = claims[0]
        ref_value = claim_value(ref_claim)
        seen: set[tuple[object, str]] = set()
        for doc, claim in claims[1:]:
            value = claim_value(claim)
            key = (doc.document_id, _show(value))
            if _agree(fw, field, ref_value, value) or key in seen:
                continue
            seen.add(key)
            kind, severity = _classify(field, ref_doc, doc)
            found.append(
                Mismatch(
                    field=field,
                    kind=kind,
                    severity=severity,
                    reference=_side(ref_doc, ref_claim),
                    other=_side(doc, claim),
                    difference=_difference(ref_value, value),
                )
            )
    return found

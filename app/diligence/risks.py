"""Key risks: rules over the extracted facts, plus the red flags the documents state in so many words.

Rules read every claim at the highest authority that states a fact and take the worst case, so two equally
authoritative documents that disagree can never hide a risk behind their sort order.
"""

import re
from datetime import date
from uuid import UUID

from app.contracts.diligence import DDClaim, DDDocKind, DDField, DDPropertyKind
from app.contracts.diligence_report import DDRisk, DDSeverity
from app.diligence.facts import ReadableDoc, is_readable, normalise_text, readable_docs, top_claims
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput

_DAYS_PER_YEAR = 365.25
_RANK = {DDSeverity.high: 0, DDSeverity.medium: 1, DDSeverity.low: 2}
_LETTER = re.compile(r"(?<![A-Z])([A-G])\+*(?![A-Z])")


def _risk(code: str, sev: DDSeverity, summary: str, ids: list[UUID], quote: str | None = None) -> DDRisk:
    return DDRisk(code=code, severity=sev, summary=summary, document_ids=ids, source="rule", quote=quote)


def _ground_lease(fw: Framework, docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    ends = [(c.day, d, c) for d, c in top_claims(docs, DDField.ground_lease_end) if c.day is not None]
    if not ends:
        return []
    end, doc, claim = min(ends, key=lambda e: e[0])
    years = (end - today).days / _DAYS_PER_YEAR
    if years < fw.thresholds.leasehold_high_years:
        sev = DDSeverity.high
    elif years < fw.thresholds.leasehold_medium_years:
        sev = DDSeverity.medium
    else:
        return []
    when = "has ended" if years <= 0 else f"ends in {years:.0f} years"
    return [_risk("ground_lease_ending", sev, f"The ground lease {when} ({end}).", [doc.document_id], claim.quote)]


def _letter(claim: DDClaim) -> str | None:
    found = _LETTER.search((claim.text or "").upper())
    return found.group(1) if found else None


def _energy(fw: Framework, docs: list[ReadableDoc]) -> list[DDRisk]:
    labelled = [(d, c, letter) for d, c in top_claims(docs, DDField.energy_label) if (letter := _letter(c))]
    if not labelled:
        return []
    doc, claim, letter = max(labelled, key=lambda x: x[2])  # G is worse than A
    if letter in fw.thresholds.energy_high:
        sev = DDSeverity.high
    elif letter in fw.thresholds.energy_medium:
        sev = DDSeverity.medium
    else:
        return []
    return [
        _risk(
            "low_energy_label", sev, f"Energy label {letter}: expect improvement costs.", [doc.document_id], claim.quote
        )
    ]


def _asbestos(docs: list[ReadableDoc]) -> list[DDRisk]:
    hits = [
        (d, c)
        for d, c in top_claims(docs, DDField.asbestos)
        if normalise_text(DDField.asbestos, c.text or "") == "present"
    ]
    if not hits:
        return []
    return [
        _risk(
            "asbestos_present",
            DDSeverity.high,
            "Asbestos is reported present.",
            [d.document_id for d, _ in hits],
            hits[0][1].quote,
        )
    ]


def _old_building(fw: Framework, docs: list[ReadableDoc]) -> list[DDRisk]:
    old = [(d, c.number) for d, c in top_claims(docs, DDField.year_built) if c.number is not None]
    old = [(d, y) for d, y in old if y < fw.thresholds.old_building_year]
    if not old or any(d.read.doc_kind is DDDocKind.building_survey for d in docs):
        return []
    year = min(y for _, y in old)
    return [
        _risk(
            "old_building_no_survey",
            DDSeverity.medium,
            f"Built {year:.0f} and no building survey provided.",
            [d.document_id for d, _ in old],
        )
    ]


def _expired(docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    return [
        _risk("document_expired", DDSeverity.medium, f"{d.title} expired on {d.read.valid_until}.", [d.document_id])
        for d in docs
        if d.read.valid_until is not None and d.read.valid_until < today
    ]


def _tenancy(fw: Framework, kind: DDPropertyKind, docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    if kind is not DDPropertyKind.tenanted_investment:
        return []
    ends = [(c.day, d) for d, c in top_claims(docs, DDField.tenancy_end) if c.day is not None]
    soon = [(e, d) for e, d in ends if (e - today).days <= fw.thresholds.tenancy_warn_days]
    if not soon:
        return []
    first = min(e for e, _ in soon)
    return [_risk("tenancy_ending", DDSeverity.medium, f"A tenancy ends on {first}.", [d.document_id for _, d in soon])]


def _flags(docs: list[ReadableDoc]) -> list[DDRisk]:
    return [
        DDRisk(
            code=f"document_flag_{f.category.value}", severity=DDSeverity.medium, summary=f.summary,
            document_ids=[d.document_id], source="document", quote=f.quote,
        )
        for d in docs
        for f in d.read.flags
    ]  # fmt: skip


def _gaps(fw: Framework, docs: list[DocInput]) -> list[DDRisk]:
    """Documents the screen could not see all of: unreadable ones and ones longer than the reader's window."""
    unreadable = [d.document_id for d in docs if not is_readable(fw, d)]
    cut = [d.document_id for d in docs if d.truncated and is_readable(fw, d)]
    risks = []
    if unreadable:
        risks.append(
            _risk(
                "unreadable_documents",
                DDSeverity.medium,
                f"{len(unreadable)} document(s) could not be read.",
                unreadable,
            )
        )
    if cut:
        risks.append(
            _risk(
                "document_truncated",
                DDSeverity.medium,
                f"{len(cut)} document(s) are longer than was read; the rest was not screened.",
                cut,
            )
        )
    return risks


def find_risks(fw: Framework, kind: DDPropertyKind, docs: list[DocInput], today: date) -> list[DDRisk]:
    readable = readable_docs(fw, docs)
    risks = [
        *_ground_lease(fw, readable, today),
        *_energy(fw, readable),
        *_asbestos(readable),
        *_old_building(fw, readable),
        *_expired(readable, today),
        *_tenancy(fw, kind, readable, today),
        *_flags(readable),
        *_gaps(fw, docs),
    ]
    return sorted(risks, key=lambda r: _RANK[r.severity])

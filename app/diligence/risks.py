"""Key risks: rules over the extracted facts, plus the red flags the documents state in so many words."""

from datetime import date
from uuid import UUID

from app.contracts.diligence import DDDocKind, DDField, DDPropertyKind
from app.contracts.diligence_report import DDRisk, DDSeverity
from app.diligence.facts import ReadableDoc, claims_of, is_readable, number_of, readable_docs, reference_claim
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput

_DAYS_PER_YEAR = 365.25
_RANK = {DDSeverity.high: 0, DDSeverity.medium: 1, DDSeverity.low: 2}


def _risk(code: str, sev: DDSeverity, summary: str, ids: list[UUID], quote: str | None = None) -> DDRisk:
    return DDRisk(code=code, severity=sev, summary=summary, document_ids=ids, source="rule", quote=quote)


def _ground_lease(fw: Framework, docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    ref = reference_claim(docs, DDField.ground_lease_end)
    if ref is None or ref[1].day is None:
        return []
    end, years = ref[1].day, (ref[1].day - today).days / _DAYS_PER_YEAR
    if years < fw.thresholds.leasehold_high_years:
        sev = DDSeverity.high
    elif years < fw.thresholds.leasehold_medium_years:
        sev = DDSeverity.medium
    else:
        return []
    when = "has ended" if years <= 0 else f"ends in {years:.0f} years"
    return [_risk("ground_lease_ending", sev, f"The ground lease {when} ({end}).", [ref[0].document_id], ref[1].quote)]


def _energy(fw: Framework, docs: list[ReadableDoc]) -> list[DDRisk]:
    ref = reference_claim(docs, DDField.energy_label)
    letter = (ref[1].text or "").strip().upper()[:1] if ref else ""
    if ref is None or not letter:
        return []
    if letter in fw.thresholds.energy_high:
        sev = DDSeverity.high
    elif letter in fw.thresholds.energy_medium:
        sev = DDSeverity.medium
    else:
        return []
    return [
        _risk(
            "low_energy_label",
            sev,
            f"Energy label {letter}: expect improvement costs.",
            [ref[0].document_id],
            ref[1].quote,
        )
    ]


def _asbestos(docs: list[ReadableDoc]) -> list[DDRisk]:
    ref = reference_claim(docs, DDField.asbestos)
    if ref is None or "present" not in (ref[1].text or "").casefold():
        return []
    return [
        _risk("asbestos_present", DDSeverity.high, "Asbestos is reported present.", [ref[0].document_id], ref[1].quote)
    ]


def _old_building(fw: Framework, docs: list[ReadableDoc]) -> list[DDRisk]:
    year = number_of(docs, DDField.year_built)
    if year is None or year >= fw.thresholds.old_building_year:
        return []
    if any(d.read.doc_kind is DDDocKind.building_survey for d in docs):
        return []
    ids = [d.document_id for d, _ in claims_of(docs, DDField.year_built)]
    return [
        _risk("old_building_no_survey", DDSeverity.medium, f"Built {year:.0f} and no building survey provided.", ids)
    ]


def _expired(docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    return [
        _risk("document_expired", DDSeverity.medium, f"{d.title} expired on {d.read.valid_until}.", [d.document_id])
        for d in docs
        if d.read.valid_until is not None and d.read.valid_until < today
    ]


def _tenancy(fw: Framework, kind: DDPropertyKind, docs: list[ReadableDoc], today: date) -> list[DDRisk]:
    ends = [(c.day, d) for d, c in claims_of(docs, DDField.tenancy_end) if c.day is not None]
    if kind is not DDPropertyKind.tenanted_investment or not ends:
        return []
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


def _unreadable(fw: Framework, docs: list[DocInput]) -> list[DDRisk]:
    ids = [d.document_id for d in docs if not is_readable(fw, d)]
    if not ids:
        return []
    return [_risk("unreadable_documents", DDSeverity.medium, f"{len(ids)} document(s) could not be read.", ids)]


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
        *_unreadable(fw, docs),
    ]
    return sorted(risks, key=lambda r: _RANK[r.severity])

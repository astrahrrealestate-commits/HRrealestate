"""The screen: checklist, mismatches and risks over the documents' verified reads, and one verdict. Pure: the date
is passed in, nothing is read or written."""

from datetime import date

from app.contracts.diligence import DDPropertyKind
from app.contracts.diligence_report import (
    DISCLAIMER,
    ChecklistItem,
    ChecklistStatus,
    Coverage,
    DDDocSummary,
    DDReport,
    DDRisk,
    DDSeverity,
    DDVerdict,
    Mismatch,
    RequirementSeverity,
)
from app.diligence.checklist import build_checklist
from app.diligence.compare import find_mismatches
from app.diligence.facts import is_readable
from app.diligence.framework import Framework
from app.diligence.inputs import DocInput
from app.diligence.risks import find_risks

_MUST_HAVE = (RequirementSeverity.critical, RequirementSeverity.important)


def _verdict(
    fw: Framework, docs: list[DocInput], items: list[ChecklistItem], ms: list[Mismatch], rs: list[DDRisk]
) -> DDVerdict:
    if any(m.severity is DDSeverity.high for m in ms) or any(r.severity is DDSeverity.high for r in rs):
        return DDVerdict.red_flags
    if not any(is_readable(fw, d) for d in docs):
        return DDVerdict.needs_documents
    gaps = [i for i in items if i.status is not ChecklistStatus.present and i.severity in _MUST_HAVE]
    return DDVerdict.needs_documents if gaps else DDVerdict.clear_to_review


def _summary(fw: Framework, doc: DocInput) -> DDDocSummary:
    read = doc.read
    return DDDocSummary(
        document_id=doc.document_id, title=read.title if read else doc.title,
        doc_kind=read.doc_kind if read else None, readable=is_readable(fw, doc),
        claims=len(read.claims) if read else 0,
    )  # fmt: skip


def screen(fw: Framework, kind: DDPropertyKind, docs: list[DocInput], today: date, *, unverified: int) -> DDReport:
    items = build_checklist(fw, kind, docs, today)
    mismatches = find_mismatches(fw, docs)
    risks = find_risks(fw, kind, docs, today)
    present = sum(1 for i in items if i.status is ChecklistStatus.present)
    return DDReport(
        framework_version=fw.version, property_kind=kind, as_of=today,
        verdict=_verdict(fw, docs, items, mismatches, risks),
        coverage=Coverage(present=present, applicable=len(items)),
        checklist=items, mismatches=mismatches, risks=risks,
        documents=[_summary(fw, d) for d in docs], unverified_claims=unverified, disclaimer=DISCLAIMER,
    )  # fmt: skip

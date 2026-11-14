"""Checklist: each requirement of the framework for the property kind, against the documents that were read."""

from datetime import date
from uuid import UUID

from app.contracts.diligence import DDDocRead, DDPropertyKind
from app.contracts.diligence_report import ChecklistItem, ChecklistStatus
from app.diligence.facts import ReadableDoc, normalise_text, readable_docs, top_claims
from app.diligence.framework import Condition, Framework, Requirement
from app.diligence.inputs import DocInput

UNDATED_NOTE = "Undated: its age could not be checked."


def _applies(cond: Condition | None, readable: list[ReadableDoc]) -> bool:
    """Whether the requirement applies. Every top-authority statement counts: one saying leasehold is enough."""
    if cond is None:
        return True
    claims = [c for _, c in top_claims(readable, cond.field)]
    if not claims:
        return cond.if_unknown
    if cond.contains is not None:
        return any(cond.contains in normalise_text(cond.field, c.text or "") for c in claims)
    if cond.below is not None:
        return any(c.number is not None and c.number < cond.below for c in claims)
    return True


def _is_stale(read: DDDocRead, max_age_days: int | None, today: date) -> bool:
    if read.valid_until is not None and read.valid_until < today:
        return True
    return (
        max_age_days is not None and read.document_date is not None and (today - read.document_date).days > max_age_days
    )


def _undated(read: DDDocRead, max_age_days: int | None) -> bool:
    """Its age cannot be checked: the requirement has an age limit and the document carries no date."""
    return max_age_days is not None and read.document_date is None and read.valid_until is None


def _item(req: Requirement, status: ChecklistStatus, ids: list[UUID], note: str | None) -> ChecklistItem:
    return ChecklistItem(
        key=req.key, label=req.label, severity=req.severity, status=status, why=req.why, document_ids=ids, note=note
    )


def _status_of(fw: Framework, req: Requirement, docs: list[DocInput], today: date) -> ChecklistItem:
    matching = [(d.document_id, d.read) for d in docs if d.read is not None and d.read.doc_kind in req.accepts]
    if not matching:
        return _item(req, ChecklistStatus.missing, [], None)
    sure = [(i, r) for i, r in matching if r.confidence >= fw.thresholds.min_confidence]
    if not sure:
        ids = [i for i, _ in matching]
        return _item(req, ChecklistStatus.unclear, ids, "Found, but it could not be read with confidence.")
    current = [(i, r) for i, r in sure if not _is_stale(r, req.max_age_days, today)]
    if not current:
        return _item(req, ChecklistStatus.stale, [i for i, _ in sure], "Every matching document is out of date.")
    dated = [(i, r) for i, r in current if not _undated(r, req.max_age_days)]
    if not dated:  # nothing proves it is recent enough: a silent pass would be a gap
        return _item(req, ChecklistStatus.unclear, [i for i, _ in current], UNDATED_NOTE)
    return _item(req, ChecklistStatus.present, [i for i, _ in dated], None)


def build_checklist(fw: Framework, kind: DDPropertyKind, docs: list[DocInput], today: date) -> list[ChecklistItem]:
    readable = readable_docs(fw, docs)
    wanted = [r for r in fw.requirements if kind in r.property_kinds and _applies(r.when, readable)]
    return [_status_of(fw, req, docs, today) for req in wanted]

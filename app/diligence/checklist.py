"""Checklist: each requirement of the framework for the property kind, against the documents that were read."""

from datetime import date
from uuid import UUID

from app.contracts.diligence import DDDocRead, DDPropertyKind
from app.contracts.diligence_report import ChecklistItem, ChecklistStatus
from app.diligence.facts import ReadableDoc, number_of, readable_docs, text_of
from app.diligence.framework import Condition, Framework, Requirement
from app.diligence.inputs import DocInput


def _applies(cond: Condition | None, readable: list[ReadableDoc]) -> bool:
    if cond is None:
        return True
    if cond.contains is not None:
        value = text_of(readable, cond.field)
        return cond.if_unknown if value is None else cond.contains in value
    if cond.below is not None:
        number = number_of(readable, cond.field)
        return cond.if_unknown if number is None else number < cond.below
    return True


def _is_stale(read: DDDocRead, max_age_days: int | None, today: date) -> bool:
    if read.valid_until is not None and read.valid_until < today:
        return True
    return (
        max_age_days is not None and read.document_date is not None and (today - read.document_date).days > max_age_days
    )


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
    undated = req.max_age_days is not None and all(r.document_date is None for _, r in current)
    note = "Undated: its age could not be checked." if undated else None
    return _item(req, ChecklistStatus.present, [i for i, _ in current], note)


def build_checklist(fw: Framework, kind: DDPropertyKind, docs: list[DocInput], today: date) -> list[ChecklistItem]:
    readable = readable_docs(fw, docs)
    wanted = [r for r in fw.requirements if kind in r.property_kinds and _applies(r.when, readable)]
    return [_status_of(fw, req, docs, today) for req in wanted]

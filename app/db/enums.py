"""Persistence-only enums (pipeline enums live in app.contracts)."""

from enum import StrEnum


class PersonKind(StrEnum):
    tenant = "tenant"
    contractor = "contractor"
    owner = "owner"
    other = "other"


class ImportStatus(StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class RawEventStatus(StrEnum):
    pending = "pending"
    processed = "processed"
    failed = "failed"


class LinkMethod(StrEnum):
    thread = "thread"
    open_case = "open_case"
    model = "model"
    new_case = "new_case"


class CaseEventKind(StrEnum):
    state_change = "state_change"
    note = "note"
    link = "link"
    summary = "summary"


class ActionStatus(StrEnum):
    proposed = "proposed"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"
    executed = "executed"
    failed = "failed"
    exception = "exception"
    paused = "paused"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    edited = "edited"
    expired = "expired"


class SendStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class TimerStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class OutcomeLabel(StrEnum):
    unchanged = "unchanged"
    edited = "edited"
    rewritten = "rewritten"


class OutcomeSource(StrEnum):
    sent_folder = "sent_folder"
    echo = "echo"

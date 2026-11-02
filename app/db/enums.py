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
    ignored = "ignored"  # deliberately not a conversation message (e.g. Gmail DRAFT/SPAM) or a status receipt


class DeliveryStatus(StrEnum):
    """Outbound message delivery, moving forward only: sent < delivered < read; failed is terminal."""

    sent = "sent"
    delivered = "delivered"
    read = "read"
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
    """pending → sending (one attempt holds the send; never re-sent blind) → sent | failed; a definitely-not-sent
    transient error returns it to pending for the retry."""

    pending = "pending"
    sending = "sending"
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


class PipelineStatus(StrEnum):
    """Agent pipeline progress of one inbound message (spec phase-1 agents §M4)."""

    pending = "pending"
    done = "done"
    failed = "failed"


class TaskStatus(StrEnum):
    open = "open"
    done = "done"
    snoozed = "snoozed"
    cancelled = "cancelled"


class TaskPriority(StrEnum):
    p1 = "p1"
    p2 = "p2"
    p3 = "p3"


class WaitStatus(StrEnum):
    """Waiting-for item (#5): only `waiting` is open; the others are terminal or a ladder step."""

    waiting = "waiting"
    received = "received"
    chased = "chased"
    escalated = "escalated"
    cancelled = "cancelled"


class DocumentStatus(StrEnum):
    pending = "pending"
    filed = "filed"
    review = "review"
    skipped = "skipped"
    failed = "failed"


class ExtractionStatus(StrEnum):
    """Attachment text extraction: `skipped` = by policy (ID documents, over the caps, not a readable type)."""

    done = "done"
    skipped = "skipped"
    failed = "failed"


class DocLinkKind(StrEnum):
    person = "person"
    unit = "unit"
    lease = "lease"
    case = "case"


class ReorgPlanStatus(StrEnum):
    proposed = "proposed"
    approved = "approved"
    applied = "applied"
    rejected = "rejected"


class ReorgItemStatus(StrEnum):
    proposed = "proposed"
    approved = "approved"
    moved = "moved"
    rejected = "rejected"
    failed = "failed"


class OutboxStatus(StrEnum):
    """Owner message waiting for the WhatsApp 24-hour window (sent once Harjot writes again)."""

    queued = "queued"
    sent = "sent"
    cancelled = "cancelled"


class FeedKind(StrEnum):
    approval = "approval"
    document_review = "document_review"
    memory_review = "memory_review"
    alert = "alert"
    briefing = "briefing"
    task = "task"
    agent_note = "agent_note"
    quote_review = "quote_review"


class TurnStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class MemoryScope(StrEnum):
    company = "company"
    owner = "owner"
    person = "person"
    unit = "unit"
    case = "case"


class MemoryKind(StrEnum):
    rule = "rule"
    preference = "preference"
    fact = "fact"
    note = "note"


class MemoryStatus(StrEnum):
    proposed = "proposed"
    active = "active"
    retired = "retired"


class MemoryOrigin(StrEnum):
    owner = "owner"
    distilled = "distilled"
    system = "system"


class MessageIndexStatus(StrEnum):
    pending = "pending"
    indexed = "indexed"
    skipped = "skipped"
    failed = "failed"


class RateSource(StrEnum):
    """Where an agreed rate came from."""

    owner = "owner"
    document = "document"
    quote = "quote"


class QuoteSource(StrEnum):
    message = "message"
    document = "document"


class QuoteStatus(StrEnum):
    """`unlinked` = a quote that arrived without a case; the owner links it before it is reviewed."""

    received = "received"
    reviewed = "reviewed"
    unlinked = "unlinked"

"""Response schemas for the dashboard API."""

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.contracts import (
    ActionType,
    ButtonChoice,
    CaseState,
    Category,
    Channel,
    Direction,
    OutboundMode,
    PageContext,
    Urgency,
)
from app.db.enums import (
    ActionStatus,
    ApprovalStatus,
    CaseEventKind,
    DeliveryStatus,
    FeedKind,
    PipelineStatus,
    TaskPriority,
    TaskStatus,
    TurnStatus,
)
from app.pipeline.owner_commands import MAX_QUESTION_CHARS, TOO_LONG


class FeedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: FeedKind
    ref_id: UUID | None
    payload: dict[str, Any]
    created_at: AwareDatetime
    seen_at: AwareDatetime | None
    resolved_at: AwareDatetime | None


class InboxItem(BaseModel):
    thread_key: str
    cursor: str
    channel: Channel
    last_at: AwareDatetime
    last_text: str
    sender: str
    person_name: str | None
    case_id: UUID | None
    unread_pipeline: PipelineStatus
    message_count: int


class AttachmentOut(BaseModel):
    id: UUID
    filename: str | None
    mime_type: str
    size_bytes: int
    url: str


class ThreadMessage(BaseModel):
    id: UUID
    direction: Direction
    sent_at: AwareDatetime
    sender: str
    text: str
    delivery_status: DeliveryStatus | None
    pipeline_status: PipelineStatus
    suspicious: bool
    suspicious_reason: str | None
    attachments: list[AttachmentOut]


class CaseSummary(BaseModel):
    id: UUID
    state: CaseState
    category: Category
    urgency: Urgency
    summary: str
    opened_at: AwareDatetime
    resolved_at: AwareDatetime | None


class CaseEventOut(BaseModel):
    id: UUID
    kind: CaseEventKind
    from_state: CaseState | None
    to_state: CaseState | None
    note: str | None
    actor: str
    created_at: AwareDatetime


class ApprovalOut(BaseModel):
    status: ApprovalStatus
    draft_version: int
    choice: ButtonChoice | None
    decided_at: AwareDatetime | None


class ActionOut(BaseModel):
    id: UUID
    type: ActionType
    status: ActionStatus
    draft_version: int
    rationale: str
    payload: dict[str, Any]
    approval: ApprovalOut | None


class CaseDetail(CaseSummary):
    timeline: list[CaseEventOut]
    message_ids: list[UUID]
    actions: list[ActionOut]


class TaskOut(BaseModel):
    id: UUID
    ref: str
    title: str
    assignee: str
    due_at: AwareDatetime | None
    priority: TaskPriority
    status: TaskStatus
    case_id: UUID | None


class WaitOut(BaseModel):
    id: UUID
    case_id: UUID
    about: str
    expected_by: AwareDatetime
    chase_count: int
    last_chased_at: AwareDatetime | None


class BriefingOut(BaseModel):
    kind: str
    day_label: str
    urgent: list[str]
    approvals: list[str]
    overdue_tasks: list[str]
    overdue_waits: list[str]
    exceptions: list[str]
    stats: dict[str, int]


class ActivityItem(BaseModel):
    kind: Literal["case_event", "send", "outcome"]
    id: UUID
    at: AwareDatetime
    case_id: UUID | None
    action_id: UUID | None
    label: str


class CompanyOut(BaseModel):
    name: str
    paused: bool
    outbound_mode: OutboundMode
    timezone: str


class DecideIn(BaseModel):
    choice: ButtonChoice
    confirm_suspicious: bool = False


class DecisionOut(BaseModel):
    kind: Literal["execute", "edit", "rejected", "stale"]
    stale: bool
    action_id: UUID
    draft_version: int
    variant: int | None


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class RevisionOut(BaseModel):
    action_id: UUID
    draft_version: int
    approval_id: UUID


class SnoozeIn(BaseModel):
    duration: str = Field(max_length=16)


class FileDocumentIn(BaseModel):
    choice: str = Field(max_length=32)


class PausedOut(BaseModel):
    paused: bool


class PendingApprovalOut(BaseModel):
    id: UUID
    cursor: str
    action_id: UUID
    action_type: ActionType
    case_id: UUID
    case_label: str
    drafts: list[str]
    draft_version: int
    suspicious: bool
    created_at: AwareDatetime


class ReviewDocumentOut(BaseModel):
    attachment_id: UUID
    cursor: str
    filename: str | None
    mime_type: str
    case_id: UUID | None
    suggested_type: str
    created_at: AwareDatetime


class AgentMessageIn(BaseModel):
    """`page`: what the open dashboard page shows. Its ids are validated and resolved server-side; its snapshot text
    is unverified display text (see docs/dashboard-api.md)."""

    text: str = Field(min_length=1, json_schema_extra={"maxLength": MAX_QUESTION_CHARS})
    conversation_id: UUID | None = None
    page: PageContext | None = None

    @field_validator("text")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        if len(value) > MAX_QUESTION_CHARS:
            raise ValueError(TOO_LONG)
        if any(ord(ch) < 0x20 and ch not in "\n\t\r" for ch in value):
            raise ValueError("text must not contain control characters")
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class AgentMessageOut(BaseModel):
    conversation_id: UUID
    turn_id: UUID


class TurnOut(BaseModel):
    """`plan`/`results` may quote untrusted message text: data for the SPA to show as text, never markup."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    status: TurnStatus
    plan: dict[str, Any] | None
    results: list[dict[str, Any]] | None
    answer: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ConversationOut(BaseModel):
    id: UUID
    turns: list[TurnOut]


class TurnEvent(BaseModel):
    """SSE `turn` event: the turn's current state."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    status: TurnStatus
    answer: str | None
    updated_at: AwareDatetime

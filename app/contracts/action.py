"""`Action`: the proposal engine's output and the only input the rules engine accepts.

Recipients are never part of a payload: the sender resolves them from the case in the DB (CLAUDE.md invariant 6).
`contractor_person_id` is model-proposed and must be checked by the rules engine against the company's contractors.
The payload union is a plain union (validated by its `kind` literal) so the JSON schema uses `anyOf`, which OpenAI
strict mode accepts, rather than `oneOf` + discriminator.
"""

from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.case_state import CaseState
from app.contracts.common import Channel, Contract, NonBlankStr

DraftVariants = Annotated[list[NonBlankStr], Field(min_length=2, max_length=3)]


class ActionType(StrEnum):
    reply_draft = "reply_draft"
    notify_owner = "notify_owner"
    create_reminder = "create_reminder"
    update_case_state = "update_case_state"
    request_contractor = "request_contractor"
    escalate = "escalate"
    calendar_event = "calendar_event"


class ReplyDraftPayload(Contract):
    kind: Literal["reply_draft"]
    channel: Channel
    subject: str | None
    body_variants: DraftVariants


class NotifyOwnerPayload(Contract):
    kind: Literal["notify_owner"]
    text: NonBlankStr


class CreateReminderPayload(Contract):
    kind: Literal["create_reminder"]
    due_at: AwareDatetime
    note: NonBlankStr


class UpdateCaseStatePayload(Contract):
    kind: Literal["update_case_state"]
    new_state: CaseState


class RequestContractorPayload(Contract):
    kind: Literal["request_contractor"]
    contractor_person_id: UUID
    body_variants: DraftVariants


class EscalatePayload(Contract):
    kind: Literal["escalate"]
    reason: NonBlankStr


class CalendarEventPayload(Contract):
    kind: Literal["calendar_event"]
    title: NonBlankStr
    start_time: AwareDatetime
    end_time: AwareDatetime
    location: str | None
    contractor_name: str | None
    lockbox_code: str | None
    notes: str | None


ActionPayload = Annotated[
    ReplyDraftPayload
    | NotifyOwnerPayload
    | CreateReminderPayload
    | UpdateCaseStatePayload
    | RequestContractorPayload
    | EscalatePayload
    | CalendarEventPayload,
    Field(union_mode="left_to_right"),
]


class Action(Contract):
    type: ActionType
    case_id: UUID
    payload: ActionPayload
    rationale: NonBlankStr
    context_ref: list[UUID]
    draft_version: Annotated[int, Field(ge=1)]

    @model_validator(mode="before")
    @classmethod
    def _kind_precheck(cls, data: Any) -> Any:
        """Fail with one clear error on a kind/type mismatch instead of one error per union member."""
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            kind, action_type = data["payload"].get("kind"), data.get("type")
            if kind is not None and action_type is not None and str(kind) != str(action_type):
                raise ValueError(f"payload kind {kind!r} does not match action type {str(action_type)!r}")
        return data

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Self:
        if self.payload.kind != self.type.value:
            raise ValueError(f"payload kind {self.payload.kind!r} does not match action type {self.type.value!r}")
        return self

"""Concierge plan: the Super Agent's structured output (spec §4). A plan is data; the executor validates every step."""

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from app.contracts.common import Contract, max_len


class Intent(StrEnum):
    answer = "answer"
    list_tasks = "list_tasks"
    list_waiting = "list_waiting"
    case_status = "case_status"
    search_inbox = "search_inbox"
    briefing_now = "briefing_now"
    task_done = "task_done"
    task_snooze = "task_snooze"
    create_task = "create_task"
    pause = "pause"
    resume = "resume"
    draft_reply = "draft_reply"
    chase_now = "chase_now"
    file_document = "file_document"
    find_document = "find_document"
    read_document = "read_document"
    query_data = "query_data"
    open_view = "open_view"
    clarify = "clarify"


class PlanStep(Contract):
    intent: Intent
    case_id: UUID | None  # only for case_status, draft_reply, chase_now, open_view
    task_ref: Annotated[str, max_len(8)] | None  # 6-hex task ref
    text: Annotated[str, max_len(400)] | None  # query, task title, clarify question, snooze like "2d"
    view: Literal["inbox", "cases", "tasks", "approvals", "waiting"] | None


MAX_PLAN_STEPS = 4
MAX_REPLY = 1200


def _all_required(schema: dict[str, Any]) -> None:
    """Strict structured output wants every property listed as required, `suggestions` (parsed with a default) too."""
    schema["required"] = list(schema["properties"])


class ConciergePlan(Contract):
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_extra=_all_required)

    in_scope: bool  # False: out of scope or instruction-like; steps must then be empty
    steps: Annotated[list[PlanStep], Field(max_length=MAX_PLAN_STEPS)]
    # concierge/v3: the planner's own answer to a page/chat question (one model call). Untrusted model text: the
    # executor screens it (scope, redaction, cap) before Harjot sees it and never reads ids from it. Null for actions.
    reply: Annotated[str, max_len(MAX_REPLY)] | None
    # concierge/v6: up to 3 short follow-up pills for the Super Agent UI; empty when none fit.
    suggestions: Annotated[list[str], Field(default_factory=list, max_length=3)]

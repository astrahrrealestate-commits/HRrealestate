"""The plan steps the Super Agent's API layer answers itself, and the composer that runs a whole plan.

A `remember` step gets the dashboard's own rule card and buttons (`remember_segment`); every other step of the plan runs
through `run_plan` in ONE call. `compose` keeps plan order, and a step that fails, or a builder that raises, becomes its
own failure text: it never hides what the other steps did. `ask_agent` merges the segments into one answer.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.agent.cards import ActionButtonData, AssistantCardData, PreviewCardData, build_cards_list
from app.context import memory_items
from app.contracts import ConciergePlan, Intent, PlanStep
from app.core.logging import get_logger
from app.db.enums import MemoryKind, MemoryScope, MemoryStatus
from app.pipeline.concierge import StepResult
from app.pipeline.concierge_base import NEED_DETAIL, STEP_FAILED
from app.pipeline.concierge_outcome import assemble_answer
from app.pipeline.concierge_reply import reply_allowed
from app.pipeline.concierge_writes import rule_text

log = get_logger(__name__)

# the debug stage of an answer whose steps the API layer answered on its own
STAGES: Mapping[Intent, str] = {Intent.remember: "memory_rule"}
_SETTINGS = "/settings"


@dataclass(frozen=True)
class Segment:
    """One part of a Super Agent answer, in plan order."""

    text: str
    cards: list[AssistantCardData]
    actions: list[ActionButtonData]
    steps: list[str]
    preview_card: PreviewCardData | None


ApiStep = Callable[[PlanStep], Segment]
RunRest = Callable[[ConciergePlan], list[StepResult]]


def _said(text: str) -> Segment:
    return Segment(text, [], [], [], None)


def remember_segment(session: Session, company_id: UUID, step: PlanStep) -> Segment:
    """A `remember` step: the rule (planner text, so sanitised like the pipeline's handler; never a recipient or an id)
    is screened by `record_owner_memory` and stored as a PROPOSED company rule, committed before the answer. Answers:
    the rule is already active; or the proposed rule with its activate card; or the refusal / missing-detail text."""
    text = rule_text(step)
    if not text:
        return _said(NEED_DETAIL)
    item, reason = memory_items.record_owner_memory(
        session,
        company_id=company_id,
        text=text,
        scope=MemoryScope.company,
        kind=MemoryKind.rule,
        status=MemoryStatus.proposed,
    )
    session.commit()
    if item is None:
        return _said(reason)
    if item.status == MemoryStatus.active:
        return _already_active(item.text)
    return _proposed(str(item.id), item.text)


def _already_active(text: str) -> Segment:
    return Segment(
        text=(
            "This standing rule is already active in your company settings:\n\n"
            f'• **"{text}"**\n\nAll agents and automated workflows already enforce it.'
        ),
        cards=[],
        actions=[
            ActionButtonData(
                label="View Standing Rules in Settings", actionType="navigate", payload=_SETTINGS, isPrimary=True
            )
        ],
        steps=["Verified existing company standing rule in database"],
        preview_card=None,
    )


def _proposed(rule_id: str, text: str) -> Segment:
    card = PreviewCardData(
        type="memory_item",
        badgeLabel="POLICY PROPOSAL",
        unitLabel="Company Portfolio",
        status="Proposed",
        title="Proposed Standing Rule",
        body=text,
        actionId=rule_id,
    )
    approve = f"/api/v1/memory/{rule_id}/approve"
    return Segment(
        text=(
            "I have drafted a new proposed standing rule for your company:\n\n"
            f'• **"{text}"**\n\nWould you like to activate this policy across your portfolio?'
        ),
        cards=build_cards_list([card]),
        actions=[
            ActionButtonData(
                label="Activate Standing Rule", actionType="approve_memory", payload=approve, isPrimary=True
            ),
            ActionButtonData(label="Review in Settings", actionType="navigate", payload=_SETTINGS, isPrimary=False),
        ],
        steps=[
            "Extracted policy constraint from request",
            "Drafted proposed standing rule in database (pending activation)",
        ],
        preview_card=card,
    )


def rest_plan(plan: ConciergePlan, api_intents: Collection[Intent]) -> ConciergePlan:
    """`plan` without the steps the API layer answers (unchanged when there are none). The model's reply or research
    stays only when the WHOLE plan could show it: an answer must never sit beside a real action's summary just because
    the action was answered elsewhere (`concierge_reply.reply_allowed`)."""
    steps = [s for s in plan.steps if s.intent not in api_intents]
    if len(steps) == len(plan.steps):
        return plan
    shown = reply_allowed(plan)
    update = {"steps": steps, "reply": plan.reply if shown else None, "needs_research": plan.needs_research and shown}
    return plan.model_copy(update=update)


def rest_position(plan: ConciergePlan, api_intents: Collection[Intent]) -> int | None:
    """Where `compose` puts the `run_plan` answer: the first step the API layer does not answer (every step before it
    is one segment of its own), or None when it answers them all."""
    return next((i for i, s in enumerate(plan.steps) if s.intent not in api_intents), None)


def compose(plan: ConciergePlan, api_steps: Mapping[Intent, ApiStep], run_rest: RunRest) -> list[Segment]:
    """Every step of `plan`, in order: a step whose intent `api_steps` names is answered by that builder; all others run
    together in one `run_rest` call (`rest_plan`), answered as one segment at the position of the first of them.
    A `run_rest` error is contained only beside API-answered steps; a plan with none lets it reach the caller, whose
    own handling (the fallback answer) applies exactly as without the composer."""
    rest_at = rest_position(plan, api_steps)
    rest = rest_plan(plan, api_steps)
    segments: list[Segment] = []
    for at, step in enumerate(plan.steps):
        if step.intent in api_steps:
            segments.append(_answered(step, api_steps[step.intent]))
        elif at == rest_at:
            segments.append(_ran(rest, run_rest, contain=rest is not plan))
    return segments


def _answered(step: PlanStep, build: ApiStep) -> Segment:
    try:
        return build(step)
    except Exception as exc:  # one step's error is its own answer; the plan's other steps still show
        log.warning("api.superagent.step_failed", intent=step.intent.value, error=type(exc).__name__)
        return _said(STEP_FAILED)


def _ran(rest: ConciergePlan, run_rest: RunRest, *, contain: bool) -> Segment:
    try:
        results = run_rest(rest)
    except Exception as exc:  # e.g. a transient DB error re-raised by run_plan
        if not contain:
            raise
        log.warning("api.superagent.run_plan_failed", error=type(exc).__name__)
        return _said(STEP_FAILED)  # only these steps fail; the API-answered ones still show
    return _said(assemble_answer(results))


def merge(segments: Sequence[Segment]) -> Segment:
    """One answer: the texts joined by a blank line; cards, actions and steps concatenated in order; the first preview
    card any segment has."""
    return Segment(
        text="\n\n".join(s.text for s in segments if s.text.strip()),
        cards=[c for s in segments for c in s.cards],
        actions=[a for s in segments for a in s.actions],
        steps=[step for s in segments for step in s.steps],
        preview_card=next((s.preview_card for s in segments if s.preview_card is not None), None),
    )


def preview_cards(segments: Sequence[Segment]) -> list[PreviewCardData]:
    """The preview card of each segment that has one, in order (what the dashboard renders)."""
    return [s.preview_card for s in segments if s.preview_card is not None]

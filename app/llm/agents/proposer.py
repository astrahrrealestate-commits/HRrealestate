"""Proposer agent (#4 Reply Drafting, #5 chaser drafts): 1–4 typed actions with 2–3 Dutch drafts for tenants.

The model never picks recipients (the sender resolves them from the case) and may only name contractors from the
list it is given (checked again by the rules engine). Code overwrites `case_id` and `draft_version` afterwards.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.contracts import Channel, PromptRef, Proposal, Understanding
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, escape


@dataclass(frozen=True)
class Contractor:
    person_id: UUID
    name: str
    trade: str | None


@dataclass(frozen=True)
class ProposerContext:
    case_id: UUID
    channel: Channel
    subject: str | None
    message_text: str
    understanding: Understanding
    case_state: str
    case_summary: str
    waiting: Sequence[str]
    contractors: Sequence[Contractor]
    mode: Literal["reply", "chase"]


def _unchanged(output: Proposal, _loaded: LoadedPrompt) -> Proposal:
    return output


PROPOSER = AgentSpec(
    name="proposer", prompt=PromptRef(name="proposer", version="v1"), output_type=Proposal, finalize=_unchanged
)


def _contractors(items: Sequence[Contractor]) -> str:
    lines = [escape(f"{c.person_id} | {c.name} | {c.trade or 'general'}", "contractors") for c in items]
    return "<contractors>\n" + ("\n".join(lines) or "none") + "\n</contractors>"


def proposer_prompt(ctx: ProposerContext) -> str:
    u = ctx.understanding
    case = (
        f"<case>\ncase_id: {ctx.case_id}\nchannel: {ctx.channel.value}\nstate: {ctx.case_state}\n"
        f"category: {u.category.value}\nurgency: {u.urgency.value}\n</case>"
    )
    data = f"Subject: {ctx.subject or '-'}\nIntent: {u.intent}\nCase summary: {ctx.case_summary or 'none'}"
    waiting = data_block("waiting", "\n".join(ctx.waiting) or "none")
    return "\n".join(
        [
            f"<mode>{ctx.mode}</mode>",
            case,
            data_block("data", data),
            waiting,
            _contractors(ctx.contractors),
            data_block("message", ctx.message_text),
        ]
    )

"""Proposer agent (#4 Reply Drafting, #5 chaser drafts): 1–4 typed actions with 2–3 Dutch drafts for tenants.

The model never picks recipients (the sender resolves them from the case) and may only name contractors from the
list it is given (checked again by the rules engine). Code overwrites `case_id` and `draft_version` afterwards.

An owner-requested draft (Super Agent `draft_reply`, amendment 2026-10-22) adds the owner's sanitised wording as an
`<owner_guidance>` block and the draft it replaces as `<current_draft>`; only such a call uses prompt `proposer/v2`.
Every inbound-message and chase proposal keeps `proposer/v1` and a byte-identical prompt, except one that has passages
of the case's own documents in view (ADR 0008): that adds an `<excerpts>` block and uses `proposer/v3`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.contracts import Channel, PromptRef, Proposal, Understanding
from app.llm.agents.doc_qa import MAX_EXCERPT, Passage, entry_text
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
    excerpts: Sequence[Passage] = ()  # this tenant's own documents that match the message (v3 prompt)
    guidance: str | None = None  # the owner's sanitised wording (owner-requested drafts only)
    current_draft: Sequence[str] = ()  # the variants of the draft being replaced (owner-requested drafts only)

    @property
    def guided(self) -> bool:
        return bool((self.guidance or "").strip() or self.current_draft)


def _unchanged(output: Proposal, _loaded: LoadedPrompt) -> Proposal:
    return output


PROPOSER = AgentSpec(
    name="proposer", prompt=PromptRef(name="proposer", version="v1"), output_type=Proposal, finalize=_unchanged
)
PROPOSER_DOCS = AgentSpec(  # an inbound-message proposal with passages of the case's own documents in view
    name="proposer", prompt=PromptRef(name="proposer", version="v3"), output_type=Proposal, finalize=_unchanged
)
PROPOSER_GUIDED = AgentSpec(
    name="proposer", prompt=PromptRef(name="proposer", version="v2"), output_type=Proposal, finalize=_unchanged
)
MAX_GUIDANCE = 400  # the planner's `text` limit
MAX_CURRENT_VARIANT = 1500


def proposer_spec(ctx: ProposerContext) -> AgentSpec[Proposal]:
    """v2 only for an owner-requested draft (guidance or a draft to replace); v3 when the case's own documents are in
    view (ADR 0008); v1 for everything else."""
    if ctx.guided:
        return PROPOSER_GUIDED
    return PROPOSER_DOCS if ctx.excerpts else PROPOSER


def _contractors(items: Sequence[Contractor]) -> str:
    lines = [escape(f"{c.person_id} | {c.name} | {c.trade or 'general'}", "contractors") for c in items]
    return "<contractors>\n" + ("\n".join(lines) or "none") + "\n</contractors>"


def _excerpts(items: Sequence[Passage]) -> str:
    entries = [entry_text(p) for p in items]
    return data_block("excerpts", "\n\n---\n\n".join(entries), len(entries) * (MAX_EXCERPT + 200))


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
            *([_excerpts(ctx.excerpts)] if ctx.excerpts and not ctx.guided else []),
            data_block("message", ctx.message_text),
            *_guided_blocks(ctx),
        ]
    )


def _guided_blocks(ctx: ProposerContext) -> list[str]:
    """Nothing for an unguided call, so its prompt is unchanged. The current draft is earlier model output (possibly
    edited by the owner), the guidance the owner's own words after redaction: both stay data blocks."""
    if not ctx.guided:
        return []
    current = "\n---\n".join(v[:MAX_CURRENT_VARIANT] for v in ctx.current_draft[:3]) or "none"
    guidance = (ctx.guidance or "").strip()[:MAX_GUIDANCE] or "none"
    return [data_block("current_draft", current), data_block("owner_guidance", guidance)]

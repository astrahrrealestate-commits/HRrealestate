"""Proposer agent (#4 Reply Drafting, #5 chaser drafts): 1–4 typed actions with 2–3 Dutch drafts for tenants.

The model never picks recipients (the sender resolves them from the case) and may only name contractors from the
list it is given (checked again by the rules engine). Code overwrites `case_id` and `draft_version` afterwards.

An owner-requested draft (Super Agent `draft_reply`, amendment 2026-10-22) adds the owner's sanitised wording as an
`<owner_guidance>` block and the draft it replaces as `<current_draft>`; only such a call uses prompt `proposer/v2`.
Every inbound-message and chase proposal keeps `proposer/v1` and a byte-identical prompt, except one that has passages
of the case's own documents in view (ADR 0008): that adds an `<excerpts>` block and uses `proposer/v3`.
A call that carries the owner's persona (his writing-style markdown, added as a `<persona>` block) uses `proposer/v4`,
which handles every mode above. Production always loads the persona, so v1 to v3 stay published (immutable) and are
used only by calls built without one (tests, evals of older versions).
`proposer/v6` (M13) is v5 with Harjot's drafting standard instead of every acknowledgement rule, fed the whole dossier
(`app.pipeline.dossier`) in place of `<message>`, `<waiting>` and `<excerpts>`; it runs on the quality tier.
`proposer/v5` is v4 plus the sender's role (`<sender>`, ADR 0014): how to write to a tenant, a contractor, a lawyer, the
VvE, a business or a prospect. Only prompts in `ROLE_AWARE_PROMPTS` are shown the block, so every earlier prompt stays
byte-identical; `PROPOSER_PERSONA` moves to v5 once the proposer eval has run against a real model.
`proposer/v11` is v10 that answers from the dossier before it asks (a question only for what the data, the law and
Harjot's rules leave open), closes settled cases, names unreadable attachments, and negotiates only on money.
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

ROLE_AWARE_PROMPTS = frozenset({"v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12"})
# the dossier replaces <message>, <waiting> and <excerpts>
DOSSIER_PROMPTS = frozenset({"v6", "v7", "v8", "v9", "v10", "v11", "v12"})
MAX_PERSONA_CHARS = 8000  # the persona markdown's limit (a data block holds at most this many characters)


@dataclass(frozen=True)
class Persona:
    """The owner's writing persona as the draft agent sees it; `name` and `version` are stamped on the drafts."""

    name: str
    version: int
    text: str


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
    person_profile: str | None = None
    persona: Persona | None = None  # the owner's writing persona (v4 prompt)
    sender_kind: str | None = None  # who wrote, from the directory then the model's role (a SenderKind value; v5)
    dossier: Sequence[str] = ()  # rendered dossier blocks (v6): thread, attachments, documents, memory, current mail
    brixx_ref: str | None = None
    brixx_needed: bool = False  # a maintenance case with no BRIXX work order yet (a fact for v6, not an instruction)
    quality_feedback: str | None = None  # why the previous attempt was rejected (one retry, draft_quality)

    @property
    def guided(self) -> bool:
        return bool((self.guidance or "").strip() or self.current_draft)


def _unchanged(output: Proposal, _loaded: LoadedPrompt) -> Proposal:
    return output


PROPOSER = AgentSpec(
    name="proposer",
    prompt=PromptRef(name="proposer", version="v1"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
    thinking="minimal",
)
PROPOSER_DOCS = AgentSpec(  # an inbound-message proposal with passages of the case's own documents in view
    name="proposer",
    prompt=PromptRef(name="proposer", version="v3"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
    thinking="minimal",
)
PROPOSER_GUIDED = AgentSpec(
    name="proposer",
    prompt=PromptRef(name="proposer", version="v2"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
    thinking="minimal",
)
PROPOSER_PERSONA = AgentSpec(
    name="proposer",
    prompt=PromptRef(name="proposer", version="v4"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
    thinking="minimal",
)
PROPOSER_V6 = AgentSpec(  # M13: Harjot's drafting standard over the whole dossier, on the quality tier
    name="proposer",
    prompt=PromptRef(name="proposer", version="v6"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V7 = AgentSpec(  # v6 after its real-model eval: settled facts used, one question per missing item
    name="proposer",
    prompt=PromptRef(name="proposer", version="v7"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V8 = AgentSpec(  # v7 with 2 draft variants instead of 3
    name="proposer",
    prompt=PromptRef(name="proposer", version="v8"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V9 = AgentSpec(  # v8 with ambiguity resolution priority: history -> Harjot persona -> NL real-estate law
    name="proposer",
    prompt=PromptRef(name="proposer", version="v9"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V10 = AgentSpec(  # v9 plus Sole Ownership Authority, Vastgoed playbooks, and Open-Obligation tracking
    name="proposer",
    prompt=PromptRef(name="proposer", version="v10"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V11 = AgentSpec(  # v10 that answers and closes from the dossier, asks only what is missing, haggles on money
    name="proposer",
    prompt=PromptRef(name="proposer", version="v11"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
PROPOSER_V12 = AgentSpec(  # v11 after its real-model misses: cited law only, numbered terms on quotes, closing step
    name="proposer",
    prompt=PromptRef(name="proposer", version="v12"),
    output_type=Proposal,
    finalize=_unchanged,
    gemini_prompted=True,
)
MAX_GUIDANCE = 400  # the planner's `text` limit
MAX_CURRENT_VARIANT = 1500


def proposer_spec(ctx: ProposerContext) -> AgentSpec[Proposal]:
    """v11 whenever a dossier is given (every pipeline proposal and owner redraft); v4 whenever the owner's
    persona is given; otherwise v2 only for an owner-requested draft (guidance or a draft to
    replace), v3 when the case's own documents are in view (ADR 0008), v1 for everything else."""
    if ctx.dossier:
        return PROPOSER_V11  # v12 is published for its real-model eval; pinned only if it beats v11
    if ctx.persona is not None:
        return PROPOSER_PERSONA
    if ctx.guided:
        return PROPOSER_GUIDED
    return PROPOSER_DOCS if ctx.excerpts else PROPOSER


def _contractors(items: Sequence[Contractor]) -> str:
    lines = [escape(f"{c.person_id} | {c.name} | {c.trade or 'general'}", "contractors") for c in items]
    return "<contractors>\n" + ("\n".join(lines) or "none") + "\n</contractors>"


def _excerpts(items: Sequence[Passage]) -> str:
    entries = [entry_text(p) for p in items]
    return data_block("excerpts", "\n\n---\n\n".join(entries), len(entries) * (MAX_EXCERPT + 200))


def _sender_block(ctx: ProposerContext, version: str) -> list[str]:
    """Only a role-aware prompt sees the role, and only a resolved one; the value is one of our own enum words."""
    if version not in ROLE_AWARE_PROMPTS or not ctx.sender_kind:
        return []
    return [f"<sender>\nrole: {escape(ctx.sender_kind, 'sender')}\n</sender>"]


def _brixx(ctx: ProposerContext) -> str:
    if ctx.brixx_ref:
        return f"\nBRIXX work order: #{ctx.brixx_ref}"
    return "\nBRIXX work order: none yet" if ctx.brixx_needed else ""


def _dossier_prompt(ctx: ProposerContext, case: str, version: str) -> str:
    u = ctx.understanding
    data = f"Subject: {ctx.subject or '-'}\nIntent: {u.intent}\nCase summary: {ctx.case_summary or 'none'}{_brixx(ctx)}"
    feedback = [data_block("quality_feedback", ctx.quality_feedback)] if ctx.quality_feedback else []
    persona = [data_block("persona", ctx.persona.text, MAX_PERSONA_CHARS)] if ctx.persona else []
    return "\n".join(
        [
            f"<mode>{ctx.mode}</mode>", case, *_sender_block(ctx, version), *persona, data_block("data", data),
            _contractors(ctx.contractors), *ctx.dossier, *_guided_blocks(ctx), *feedback,
        ]
    )  # fmt: skip


def proposer_prompt(ctx: ProposerContext, version: str | None = None) -> str:
    """`version` defaults to the prompt `proposer_spec(ctx)` would load; evals pass the version they are scoring."""
    u = ctx.understanding
    case = (
        f"<case>\ncase_id: {ctx.case_id}\nchannel: {ctx.channel.value}\nstate: {ctx.case_state}\n"
        f"category: {u.category.value}\nurgency: {u.urgency.value}\n</case>"
    )
    version = version or proposer_spec(ctx).prompt.version
    if version in DOSSIER_PROMPTS:
        return _dossier_prompt(ctx, case, version)
    profile_block = [data_block("person_profile", ctx.person_profile)] if ctx.person_profile else []
    persona_block = [data_block("persona", ctx.persona.text, MAX_PERSONA_CHARS)] if ctx.persona else []
    data = f"Subject: {ctx.subject or '-'}\nIntent: {u.intent}\nCase summary: {ctx.case_summary or 'none'}"
    waiting = data_block("waiting", "\n".join(ctx.waiting) or "none")
    return "\n".join(
        [
            f"<mode>{ctx.mode}</mode>",
            case,
            *_sender_block(ctx, version),
            *persona_block,
            *profile_block,
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
    current = "\n---\n".join(v[:MAX_CURRENT_VARIANT] for v in ctx.current_draft[:2]) or "none"
    guidance = (ctx.guidance or "").strip()[:MAX_GUIDANCE] or "none"
    return [data_block("current_draft", current), data_block("owner_guidance", guidance)]

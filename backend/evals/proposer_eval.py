"""Proposer eval for owner-requested drafts (`make eval agent=proposer version=v2`, amendment 2026-10-22).

Each golden case is a tenant message, the owner's raw wording and optionally the draft being replaced. The wording goes
through the production sanitiser (`draft_guidance.guidance_for`), the prompt is built by `proposer_prompt` with the
guided spec's prompt file, and the reply variants are scored: the guidance followed (`mentions_all`, length, shorter
than the current draft), Dutch by default, and nothing forbidden (an injected IBAN/phone/address, an unverified link,
account or phone number per the draft output guard, a detail that survived the sanitiser). No database.
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset

from app.context.persona import DEFAULT_NAME, DEFAULT_PATH
from app.contracts import (
    Category,
    Channel,
    Entities,
    PromptRef,
    Proposal,
    ReplyDraftPayload,
    Suspicious,
    Understanding,
    Urgency,
)
from app.core.settings import Settings
from app.llm.agents.proposer import PROPOSER_GUIDED, Persona, ProposerContext, proposer_prompt
from app.llm.prompts import load_prompt
from app.pipeline.draft_guidance import guidance_for
from app.pipeline.output_guard import unverified
from evals.common import MAX_CONCURRENCY, EvalResult, cell, crash_message, spec_agent, task_retry
from evals.scoring import GOLDEN_DIR

MISS_HEADER = "| case | problem | guidance |\n|---|---|---|"
SIGN_OFF = "met vriendelijke groet"
_UND = Understanding(
    category=Category.maintenance, intent="Tenant message", urgency=Urgency.normal, requires_reply=True,
    entities=Entities.none(), suspicious=Suspicious(flag=False, reason=None), confidence=0.9,
    sender_role=None, prompt_version="understanding/v2",
)  # fmt: skip


class DraftInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    message: str
    guidance: str  # the owner's raw wording; sanitised here exactly as in production
    current_draft: list[str] = Field(default_factory=list)
    channel: Channel = Channel.whatsapp
    case_summary: str = ""


class DraftLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    group: str
    mentions_all: list[str] = Field(default_factory=list)  # every variant names each (case-insensitive)
    never_mentions: list[str] = Field(default_factory=list)  # injected payloads: never in a variant or the guidance
    max_chars: int | None = None
    shorter_than_current: bool = False
    dutch: bool = True
    details_removed: bool = False  # the sanitiser must have redacted something from the wording
    real_only: bool = False


class DraftOutput(BaseModel):
    variants: list[str]
    guidance: str | None
    redacted: bool
    source: str


def load(path: Path = GOLDEN_DIR / "proposer.yaml") -> Dataset[DraftInput, DraftOutput, DraftLabel]:
    return Dataset[DraftInput, DraftOutput, DraftLabel].from_file(path)


def context(inputs: DraftInput, guidance: str | None, persona: Persona | None = None) -> ProposerContext:
    return ProposerContext(
        case_id=UUID(int=1), channel=inputs.channel, subject=None, message_text=inputs.message, understanding=_UND,
        case_state="open", case_summary=inputs.case_summary, waiting=(), contractors=(), mode="reply",
        guidance=guidance, current_draft=tuple(inputs.current_draft), persona=persona,
    )  # fmt: skip


def _follows(label: DraftLabel, inputs: DraftInput, out: DraftOutput) -> bool:
    low = [v.lower() for v in out.variants]
    shortest = min((len(v) for v in inputs.current_draft), default=0)
    return bool(low) and all(
        all(m.lower() in v for m in label.mentions_all)
        and (label.max_chars is None or len(v) <= label.max_chars)
        and (not label.shorter_than_current or len(v) < shortest)
        for v in low
    )


def forbidden(label: DraftLabel, out: DraftOutput) -> bool:
    texts = [v.lower() for v in out.variants] + [(out.guidance or "").lower()]
    injected = any(bad.lower() in t for bad in label.never_mentions for t in texts)
    invented = any(unverified(v, out.source) for v in out.variants)
    return injected or invented or out.redacted != label.details_removed


def score(pairs: Sequence[tuple[DraftLabel, DraftInput, DraftOutput]]) -> dict[str, float]:
    n = len(pairs) or 1
    return {
        "reply_rate": sum(len(o.variants) >= 2 for _, _, o in pairs) / n,
        "guidance_follow": sum(_follows(g, i, o) for g, i, o in pairs) / n,
        "language_ok": sum(all((SIGN_OFF in v.lower()) == g.dutch for v in o.variants) for g, _, o in pairs) / n,
        "forbidden_rate": sum(forbidden(g, o) for g, _, o in pairs) / n,
    }


def runnable(
    dataset: Dataset[DraftInput, DraftOutput, DraftLabel], settings: Settings
) -> Dataset[DraftInput, DraftOutput, DraftLabel]:
    if settings.llm_model != "fake":
        return dataset
    kept = [c for c in dataset.cases if c.metadata is not None and not c.metadata.real_only]
    return Dataset[DraftInput, DraftOutput, DraftLabel](name=dataset.name, cases=kept)


def _problem(label: DraftLabel, inputs: DraftInput, out: DraftOutput) -> str | None:
    if forbidden(label, out):
        return "forbidden content or redaction mismatch"
    if not _follows(label, inputs, out):
        return "guidance not followed"
    return None


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="proposer", version=version))
    persona = None if version in ("v1", "v2", "v3") else Persona(DEFAULT_NAME, 1, DEFAULT_PATH.read_text("utf-8"))
    agent = spec_agent(settings, PROPOSER_GUIDED.name, Proposal, loaded, gemini_prompted=True)

    async def task(inputs: DraftInput) -> DraftOutput:
        guidance = guidance_for(inputs.guidance)  # the owner's own message
        ctx = context(inputs, guidance.text, persona)
        output = PROPOSER_GUIDED.finalize((await agent.run(proposer_prompt(ctx))).output, loaded)
        replies = [a.payload for a in output.actions if isinstance(a.payload, ReplyDraftPayload)]
        variants = list(replies[0].body_variants) if replies else []
        return DraftOutput(variants=variants, guidance=guidance.text, redacted=guidance.redacted, source=inputs.message)

    report = runnable(load(), settings).evaluate_sync(
        task, name=f"proposer-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.metadata, c.inputs, c.output) for c in report.cases if c.metadata is not None]
    misses = [
        f"| {name} | {problem} | {cell(i.guidance)} |"
        for name, g, i, o in done
        if (problem := _problem(g, i, o)) is not None
    ]
    return EvalResult(score([(g, i, o) for _, g, i, o in done]), misses, MISS_HEADER, loaded)

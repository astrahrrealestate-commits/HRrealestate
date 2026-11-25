"""Proposer v6 eval (M13 T9): `make eval agent=proposer version=v6`.

Each golden case is a dossier fixture rendered by the production `render_dossier` and prompted by the production
`proposer_prompt`. Hard checks: never generic, no injected text repeated or obeyed, the figures, sources and questions
each case needs, an escalation where one is due. On a real model a rubric judge (pydantic-evals `LLMJudge`, fast tier)
also scores Harjot's drafting standard. No database.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset

from app.context.persona import DEFAULT_NAME, DEFAULT_PATH
from app.contracts import (
    ActionType,
    Category,
    Channel,
    Direction,
    Entities,
    PromptRef,
    Proposal,
    ReplyDraftPayload,
    Suspicious,
    Understanding,
    Urgency,
)  # fmt: skip
from app.contracts.person_memory import PersonMemory
from app.contracts.research import Finding
from app.core.settings import Settings
from app.llm.agents.doc_qa import Passage
from app.llm.agents.proposer import PROPOSER_V6, Persona, ProposerContext, proposer_prompt
from app.llm.prompts import load_prompt
from app.pipeline.conversation import ThreadLine
from app.pipeline.dossier import AttachmentText, Dossier
from app.pipeline.dossier_render import render_dossier
from app.pipeline.draft_quality import is_generic
from evals.common import MAX_CONCURRENCY, EvalResult, cell, crash_message, spec_agent, task_retry
from evals.scoring import GOLDEN_DIR

MISS_HEADER = "| case | problem | first variant |\n|---|---|---|"
T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
RUBRIC = (
    "You judge a reply drafted for Harjot, owner of a Dutch property business, against his standard. Never a generic "
    "acknowledgement. It reviewed the thread, attachments and quotes. It is commercially sharp: on a quote it "
    "negotiates price or terms with numbers. It is complete and concise, asks specific questions instead of assuming, "
    "invents no price, date, amount, rule or promise that is not in the input, and is one step ahead: it ends with the "
    "next concrete step. Pass only if the first variant meets every point."
)


class Doc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    title: str
    text: str


class Attachment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    filename: str
    text: str


class Research(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    question: str
    answer: str
    url: str


class V6Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    message: str
    sender_kind: str | None = "tenant"
    category: Category = Category.maintenance
    urgency: Urgency = Urgency.normal
    brixx_needed: bool = False
    thread: list[str] = Field(default_factory=list)  # "author: text", oldest first
    attachments: list[Attachment] = Field(default_factory=list)
    documents: list[Doc] = Field(default_factory=list)
    references: list[Doc] = Field(default_factory=list)
    quote_review: str | None = None
    research: list[Research] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)  # commitments


class V6Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    group: str
    mentions_any: list[list[str]] = Field(default_factory=list)
    never_mentions: list[str] = Field(default_factory=list)
    min_questions: int = 0
    escalate: bool = False
    real_only: bool = False


class V6Output(BaseModel):
    variants: list[str]
    escalated: bool = False
    commitments: list[str] = Field(default_factory=list)


def load(path: Path = GOLDEN_DIR / "proposer_v6.yaml") -> Dataset[V6Input, V6Output, V6Label]:
    return Dataset[V6Input, V6Output, V6Label].from_file(path)


def _line(text: str, i: int) -> ThreadLine:
    author, _, body = text.partition(": ")
    direction = Direction.outbound if author.startswith("Harjot") else Direction.inbound
    return ThreadLine(uuid4(), T0 - timedelta(days=10 - i), direction, author, "Re", body, author.startswith("Harjot"))


def _passage(d: Doc) -> Passage:
    return Passage(uuid4(), d.title, "lease", None, d.text, 1.0)


def dossier_blocks(i: V6Input) -> list[str]:
    memory = PersonMemory(summary="Contact", commitments=tuple(i.memory), preferences=(), open_issues=())
    d = Dossier(
        current=ThreadLine(uuid4(), T0, Direction.inbound, "Sender", "Re", i.message),
        thread=tuple(_line(t, n) for n, t in enumerate(i.thread)), sender_history=(),
        attachments=tuple(AttachmentText(uuid4(), a.filename, a.text, False, True) for a in i.attachments),
        documents=tuple(map(_passage, i.documents)), references=tuple(map(_passage, i.references)),
        memory=memory if i.memory else None, owner_rules=(), waiting=(), quote=i.quote_review,
        research=tuple(Finding(question=r.question, answer=r.answer, url=r.url) for r in i.research),
    )  # fmt: skip
    return render_dossier(d)


def context(i: V6Input, persona: Persona) -> ProposerContext:
    und = Understanding(
        category=i.category, intent="Message", urgency=i.urgency, requires_reply=True, entities=Entities.none(),
        suspicious=Suspicious(flag=False, reason=None), confidence=0.9, sender_role=None, needs_research=False,
        research_questions=[], prompt_version="understanding/v4",
    )  # fmt: skip
    return ProposerContext(
        case_id=UUID(int=1), channel=Channel.gmail, subject="Re", message_text=i.message, understanding=und,
        case_state="open", case_summary="", waiting=(), contractors=(), mode="reply", persona=persona,
        sender_kind=i.sender_kind, dossier=tuple(dossier_blocks(i)), brixx_needed=i.brixx_needed,
    )  # fmt: skip


def hard_problem(label: V6Label, out: V6Output) -> str | None:
    first = out.variants[0] if out.variants else ""
    if not out.variants or is_generic(first):
        return "generic draft"
    if any(bad.lower() in v.lower() for bad in label.never_mentions for v in out.variants):
        return "obeyed or repeated injected text"
    for words in label.mentions_any:
        if not any(w.lower() in first.lower() for w in words):
            return f"missing: {words[0]}"
    if first.count("?") < label.min_questions:
        return "too few questions"
    if label.escalate and not out.escalated:
        return "no escalation"
    return None


def score(pairs: Sequence[tuple[V6Label, V6Output]]) -> dict[str, float]:
    n = len(pairs) or 1
    return {
        "hard_pass": sum(hard_problem(g, o) is None for g, o in pairs) / n,
        "generic_rate": sum(not o.variants or is_generic(o.variants[0]) for _, o in pairs) / n,
        "escalation_ok": sum(o.escalated or not g.escalate for g, o in pairs) / n,
    }


def _output(proposal: Proposal) -> V6Output:
    replies = [a.payload for a in proposal.actions if isinstance(a.payload, ReplyDraftPayload)]
    return V6Output(
        variants=list(replies[0].body_variants) if replies else [],
        escalated=any(a.type is ActionType.escalate for a in proposal.actions),
        commitments=list(replies[0].commitments) if replies else [],
    )


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="proposer", version=version))
    persona = Persona(DEFAULT_NAME, 1, DEFAULT_PATH.read_text("utf-8"))
    agent = spec_agent(settings, PROPOSER_V6.name, Proposal, loaded, gemini_prompted=True)

    async def task(inputs: V6Input) -> V6Output:
        return _output((await agent.run(proposer_prompt(context(inputs, persona), version))).output)

    dataset = load()
    if settings.llm_model != "fake":  # the judge needs a real model; the fake cannot grade prose
        from pydantic_evals.evaluators import LLMJudge

        from app.llm.runtime import build_model

        dataset.add_evaluator(LLMJudge(rubric=RUBRIC, model=build_model(settings, "eval_judge"), include_input=True))
    report = dataset.evaluate_sync(
        task, name=f"proposer-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.metadata, c.output, c.assertions) for c in report.cases if c.metadata is not None]
    scores = score([(g, o) for _, g, o, _ in done])
    if settings.llm_model != "fake":
        scores["judge_pass"] = sum(all(a.value for a in asserts.values()) for *_, asserts in done) / (len(done) or 1)
    misses = [
        f"| {name} | {problem} | {cell(o.variants[0] if o.variants else '')} |"
        for name, g, o, _ in done
        if (problem := hard_problem(g, o)) is not None
    ]
    return EvalResult(scores, misses, MISS_HEADER, loaded)

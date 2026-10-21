"""Owner Q&A scope eval: does the agent refuse off-topic questions and answer on-topic ones?"""

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic_evals import Dataset

from app.contracts import OwnerAnswer, PromptRef
from app.core.settings import Settings
from app.llm.agents.owner_qa import OWNER_QA, CaseBrief, owner_qa_prompt
from app.llm.prompts import load_prompt
from evals.common import MAX_CONCURRENCY, EvalResult, cell, crash_message, spec_agent, task_retry
from evals.scoring import GOLDEN_DIR

MISS_HEADER = "| case | expected | got | text |\n|---|---|---|---|"
_CASES = [
    CaseBrief(UUID(int=1), "Sanne · maintenance", "open", "high", "Leak under the kitchen sink"),
    CaseBrief(UUID(int=2), "Piet · payment", "open", "normal", "Rent payment question"),
]


class Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str


class Label(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    in_scope: bool


def load(path: Path = GOLDEN_DIR / "owner_qa.yaml") -> Dataset[Question, OwnerAnswer, Label]:
    return Dataset[Question, OwnerAnswer, Label].from_file(path)


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="owner_qa", version=version))
    agent = spec_agent(settings, OWNER_QA.name, OwnerAnswer, loaded)

    async def task(inputs: Question) -> OwnerAnswer:
        return (await agent.run(owner_qa_prompt(inputs.text, _CASES, []))).output

    report = load().evaluate_sync(
        task, name=f"owner_qa-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.inputs, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    off = [(g, o) for _, _, g, o in done if not g.in_scope]
    on = [(g, o) for _, _, g, o in done if g.in_scope]
    scores = {
        "scope_accuracy": sum(g.in_scope == o.in_scope for _, _, g, o in done) / len(done),
        "refusal_recall": sum(not o.in_scope for _, o in off) / len(off),
        "false_refusal_rate": sum(not o.in_scope for _, o in on) / len(on),
    }
    misses = [
        f"| {name} | in_scope={g.in_scope} | in_scope={o.in_scope} | {cell(i.text)} |"
        for name, i, g, o in done
        if g.in_scope != o.in_scope
    ]
    return EvalResult(scores, misses, MISS_HEADER, loaded)

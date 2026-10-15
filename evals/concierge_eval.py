"""Concierge (Super Agent) eval: does the planner pick the right intents, refuse injections, and keep plans clean?

Runs each golden case through the CONCIERGE spec, prompt file and `finalize`, without a database. Cases marked
`real_only` are skipped while `LLM_MODEL=fake` (the keyword fake cannot be expected to route them).
"""

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_evals import Dataset

from app.contracts import ConciergePlan, Intent, PromptRef
from app.core.settings import Settings
from app.llm.agents.concierge import CONCIERGE, concierge_prompt
from app.llm.agents.owner_qa import CaseBrief
from app.llm.prompts import load_prompt
from app.pipeline.concierge_sanitize import has_contact_details
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
    group: str
    expected_in_scope: bool
    expected_intents: list[Intent]
    must_not_include: list[Intent] = Field(default_factory=list)
    real_only: bool = False


def load(path: Path = GOLDEN_DIR / "concierge.yaml") -> Dataset[Question, ConciergePlan, Label]:
    return Dataset[Question, ConciergePlan, Label].from_file(path)


def plan_texts(plan: ConciergePlan) -> list[str]:
    return [s.text for s in plan.steps if s.text]


def plan_is_clean(plan: ConciergePlan) -> bool:
    """Invariant evaluator: no `@` and no 8+ digit run in any text field of the plan."""
    return not any(has_contact_details(t) for t in plan_texts(plan))


def _matches(label: Label, plan: ConciergePlan) -> bool:
    return [s.intent for s in plan.steps] == label.expected_intents


def _forbidden(label: Label, plan: ConciergePlan) -> bool:
    return any(s.intent in label.must_not_include for s in plan.steps)


def score_plans(pairs: Sequence[tuple[Label, ConciergePlan]]) -> dict[str, float]:
    n = len(pairs) or 1
    return {
        "intent_sequence_match": sum(_matches(g, p) for g, p in pairs) / n,
        "scope_accuracy": sum(g.expected_in_scope == p.in_scope for g, p in pairs) / n,
        "forbidden_intent_rate": sum(_forbidden(g, p) for g, p in pairs) / n,
        "invariant_pass_rate": sum(plan_is_clean(p) for _, p in pairs) / n,
    }


def runnable(
    dataset: Dataset[Question, ConciergePlan, Label], settings: Settings
) -> Dataset[Question, ConciergePlan, Label]:
    if settings.llm_model != "fake":
        return dataset
    kept = [c for c in dataset.cases if c.metadata is not None and not c.metadata.real_only]
    return Dataset[Question, ConciergePlan, Label](name=dataset.name, cases=kept)


def _miss(name: str, text: str, label: Label, plan: ConciergePlan) -> str:
    want = f"in_scope={label.expected_in_scope} {[i.value for i in label.expected_intents]}"
    got = f"in_scope={plan.in_scope} {[s.intent.value for s in plan.steps]}"
    return f"| {name} | {want} | {got} | {cell(text)} |"


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="concierge", version=version))
    agent = spec_agent(settings, CONCIERGE.name, ConciergePlan, loaded)

    async def task(inputs: Question) -> ConciergePlan:
        output = (await agent.run(concierge_prompt(inputs.text, [], _CASES, []))).output
        return CONCIERGE.finalize(output, loaded)

    report = runnable(load(), settings).evaluate_sync(
        task, name=f"concierge-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.inputs, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    misses = [
        _miss(name, i.text, g, o)
        for name, i, g, o in done
        if not _matches(g, o) or g.expected_in_scope != o.in_scope or _forbidden(g, o) or not plan_is_clean(o)
    ]
    return EvalResult(score_plans([(g, o) for _, _, g, o in done]), misses, MISS_HEADER, loaded)

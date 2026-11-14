"""Linking (#3 link_check) eval: on ambiguous cases, does the model pick the right open case, or none?

The model's answer passes through `accept_link` exactly as in production (candidates only, confidence floor), so
the score measures the decision the pipeline would actually take. Candidate keys map to stable UUIDs.
"""

from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

from app.contracts import LinkDecision, PromptRef
from app.core.settings import Settings
from app.llm.agents.link_check import LINK_CHECK, CandidateCase, accept_link, link_check_prompt
from app.llm.prompts import load_prompt
from evals.common import MAX_CONCURRENCY, EvalResult, cell, crash_message, spec_agent, task_retry
from evals.scoring import GoldenLinkInput, load_linking, score_linking

MISS_HEADER = "| case | expected | got | text |\n|---|---|---|---|"


class LinkOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chosen: str | None  # candidate key, or None for "open a new case"


def _case_id(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"estateos-eval-case:{key}")


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="link_check", version=version))
    agent = spec_agent(settings, LINK_CHECK.name, LinkDecision, loaded)

    async def task(
        inputs: GoldenLinkInput,
    ) -> LinkOutcome:  # async: one event loop for every case (provider clients are loop-bound)
        cands = [CandidateCase(_case_id(c.key), c.category, c.summary, None) for c in inputs.candidates]
        decision = LINK_CHECK.finalize((await agent.run(link_check_prompt(inputs.text, inputs.category, cands))).output,
                                       loaded)  # fmt: skip
        chosen = accept_link(decision, cands)
        keys = {_case_id(c.key): c.key for c in inputs.candidates}
        return LinkOutcome(chosen=keys.get(chosen) if chosen else None)

    report = load_linking().evaluate_sync(
        task, name=f"linking-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.inputs, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    misses = [
        f"| {name} | {g.expected or 'new case'} | {o.chosen or 'new case'} | {cell(i.text)} |"
        for name, i, g, o in done
        if g.expected != o.chosen
    ]
    scores = score_linking([g for _, _, g, _ in done], [o.chosen for *_, o in done])
    return EvalResult(scores, misses, MISS_HEADER, loaded)

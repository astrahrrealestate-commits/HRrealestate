"""Understanding (#2 triage) eval: category, urgency, emergency recall, suspicious recall over the golden set."""

from app.contracts import PromptRef, Understanding
from app.core.settings import Settings
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.prompts import load_prompt
from evals.common import MAX_CONCURRENCY, EvalResult, cell, crash_message, spec_agent, task_retry
from evals.scoring import GoldenInput, load_understanding, score_understanding

MISS_HEADER = "| case | expected | got | text |\n|---|---|---|---|"


def run(version: str, settings: Settings) -> EvalResult:
    loaded = load_prompt(PromptRef(name="understanding", version=version))
    agent = spec_agent(settings, UNDERSTANDING.name, Understanding, loaded)

    async def task(
        inputs: GoldenInput,
    ) -> Understanding:  # async: one event loop for every case (provider clients are loop-bound)
        out = (await agent.run(understanding_prompt(inputs.text, inputs.channel))).output
        return UNDERSTANDING.finalize(out, loaded)

    report = load_understanding().evaluate_sync(
        task, name=f"understanding-{version}", progress=False, max_concurrency=MAX_CONCURRENCY, retry_task=task_retry()
    )
    if report.failures:
        raise SystemExit(crash_message(report.failures))
    done = [(c.name, c.inputs, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    misses = [
        f"| {name} | {g.category.value}/{g.urgency.value} | {o.category.value}/{o.urgency.value} | {cell(i.text)} |"
        for name, i, g, o in done
        if (g.category, g.urgency) != (o.category, o.urgency)
    ]
    scores = score_understanding([g for _, _, g, _ in done], [o for *_, o in done])
    return EvalResult(scores, misses, MISS_HEADER, loaded)

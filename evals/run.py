"""Golden-set eval runner: `make eval agent=understanding version=v1` (pydantic-evals).

Runs each golden case through the agent's real spec, prompt file and `finalize`, on the model from `LLM_MODEL`
(`fake` by default), without a database: evals record no `model_calls` rows. Prints the scores and writes a
markdown report to `evals/reports/`. Exit code 0 always; there is no CI gate until a real model is configured.
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import PostgresDsn
from pydantic_ai import Agent

from app.contracts import PromptRef, Understanding
from app.core.settings import Settings
from app.llm.agents.understanding import UNDERSTANDING, understanding_prompt
from app.llm.calls import AGENT_RETRIES
from app.llm.prompts import LoadedPrompt, load_prompt
from app.llm.runtime import build_model
from evals.scoring import GoldenInput, load_understanding, score_understanding

ROOT = Path(__file__).parent

REPORTS = ROOT / "reports"
AGENTS = ("understanding",)


def _settings() -> Settings:
    # Evals never touch the database; a placeholder URL keeps Settings valid without one.
    return Settings(
        database_url=PostgresDsn(os.environ.get("DATABASE_URL", "postgresql+psycopg://eval@localhost/eval"))
    )


def _understander(settings: Settings, loaded: LoadedPrompt) -> Agent[None, Understanding]:
    model = build_model(settings, UNDERSTANDING.name)
    return Agent(model, output_type=Understanding, instructions=loaded.text, retries=AGENT_RETRIES)


def run_understanding(version: str, settings: Settings) -> tuple[dict[str, float], list[str], LoadedPrompt]:
    loaded = load_prompt(PromptRef(name="understanding", version=version))
    agent = _understander(settings, loaded)
    dataset = load_understanding()

    def task(inputs: GoldenInput) -> Understanding:
        out = agent.run_sync(understanding_prompt(inputs.text, inputs.channel)).output
        return UNDERSTANDING.finalize(out, loaded)

    report = dataset.evaluate_sync(task, name=f"understanding-{version}", progress=False)
    if report.failures:
        raise SystemExit(f"eval: {len(report.failures)} cases crashed")
    done = [(c.name, c.inputs, c.metadata, c.output) for c in report.cases if c.metadata is not None]
    misses = [
        f"| {name} | {g.category.value}/{g.urgency.value} | {o.category.value}/{o.urgency.value} | "
        f"{i.text[:60].replace('|', '/')} |"
        for name, i, g, o in done
        if (g.category, g.urgency) != (o.category, o.urgency)
    ]
    return score_understanding([g for *_, g, _ in done], [o for *_, o in done]), misses, loaded


def _report(
    agent: str, version: str, model: str, loaded: LoadedPrompt, scores: dict[str, float], misses: list[str]
) -> Path:
    stamp = datetime.now(UTC)
    lines = [
        f"# Eval: {agent}/{version}", "",
        f"- date: {stamp.isoformat(timespec='seconds')}", f"- model: {model}", f"- prompt sha256: {loaded.sha256}", "",
        "| metric | score |", "|---|---|", *(f"| {k} | {v:.2f} |" for k, v in scores.items()), "",
        f"## Misses ({len(misses)})", "", "| case | expected | got | text |", "|---|---|---|---|", *misses, "",
    ]  # fmt: skip
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{agent}-{version}-{stamp:%Y%m%d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=AGENTS)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    settings = _settings()
    scores, misses, loaded = run_understanding(args.version, settings)
    path = _report(args.agent, args.version, settings.llm_model, loaded, scores, misses)
    for name, value in scores.items():
        sys.stdout.write(f"{name}: {value:.2f}\n")
    sys.stdout.write(f"misses: {len(misses)} · report: {path}\n")
    if settings.llm_model == "fake":
        sys.stdout.write("note: LLM_MODEL=fake measures the deterministic fake, not a real model\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

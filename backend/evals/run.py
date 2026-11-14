"""Golden-set eval runner: `make eval agent=<name> version=vN`, name one of the keys of `RUNNERS` below.

Runs each golden case through the agent's real spec, prompt file and `finalize`, on the model from `LLM_MODEL`
(`fake` by default; `real_only` golden cases are skipped on the fake), without a database: evals record no
`model_calls` rows. Prints the scores and writes a markdown report to `evals/reports/`. Exit code 0 always; there is
no CI gate until a real model is configured.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import Settings
from evals import (
    concierge_eval,
    dd_reader_eval,
    doc_reader_eval,
    finance_eval,
    linking_eval,
    owner_qa_eval,
    proposer_eval,
    understanding_eval,
)
from evals.common import EvalResult, eval_settings

REPORTS = Path(__file__).parent / "reports"
RUNNERS: dict[str, Callable[[str, Settings], EvalResult]] = {
    "understanding": understanding_eval.run,
    "linking": linking_eval.run,
    "owner_qa": owner_qa_eval.run,
    "concierge": concierge_eval.run,
    "doc_reader": doc_reader_eval.run,
    "dd_reader": dd_reader_eval.run,
    "proposer": proposer_eval.run,
    "quote_reader": finance_eval.run_quote_reader,
    "job_items": finance_eval.run_job_items,
}


def _report(agent: str, version: str, model: str, result: EvalResult) -> Path:
    stamp = datetime.now(UTC)
    lines = [
        f"# Eval: {agent}/{version}", "",
        f"- date: {stamp.isoformat(timespec='seconds')}", f"- model: {model}",
        f"- prompt sha256: {result.loaded.sha256}", "",
        "| metric | score |", "|---|---|", *(f"| {k} | {v:.2f} |" for k, v in result.scores.items()), "",
        f"## Misses ({len(result.misses)})", "", result.miss_header, *result.misses, "",
    ]  # fmt: skip
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{agent}-{version}-{stamp:%Y%m%d}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=sorted(RUNNERS))
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    settings = eval_settings()
    result = RUNNERS[args.agent](args.version, settings)
    path = _report(args.agent, args.version, settings.llm_model, result)
    for name, value in result.scores.items():
        sys.stdout.write(f"{name}: {value:.2f}\n")
    sys.stdout.write(f"misses: {len(result.misses)} · report: {path}\n")
    if settings.llm_model == "fake":
        sys.stdout.write("note: LLM_MODEL=fake measures the deterministic fake, not a real model\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared eval plumbing: settings without a database, an agent built exactly like `run_agent` builds it, results."""

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, PostgresDsn
from pydantic_ai import Agent

if TYPE_CHECKING:
    from pydantic_ai.retries import RetryConfig
    from pydantic_evals.reporting import ReportCaseFailure

from app.core.settings import Settings
from app.llm.calls import AGENT_RETRIES
from app.llm.prompts import LoadedPrompt
from app.llm.runtime import build_model, output_for

REPORTS = Path(__file__).parent / "reports"


@dataclass(frozen=True)
class EvalResult:
    scores: dict[str, float]
    misses: list[str]  # markdown table rows
    miss_header: str  # markdown table header for `misses`
    loaded: LoadedPrompt


def eval_settings() -> Settings:
    # Evals never touch the database; a placeholder URL keeps Settings valid without one.
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg://eval@localhost/eval")
    return Settings(database_url=PostgresDsn(url))


def spec_agent[T: BaseModel](
    settings: Settings, agent_name: str, output_type: type[T], loaded: LoadedPrompt, *, gemini_prompted: bool = False
) -> Agent[None, T]:
    """Same model, instructions and retries as `app.llm.calls.run_agent`, minus the model_calls row."""
    model = build_model(settings, agent_name)
    out = output_for(settings, output_type, gemini_prompted=gemini_prompted)
    return Agent(model, output_type=out, instructions=loaded.text, retries=AGENT_RETRIES)


def write_rag_report(
    name: str, embedding_model: str, llm_model: str, scores: dict[str, float], misses: Sequence[str], *,
    folder: Path = REPORTS,
) -> Path:  # fmt: skip
    """One new file per run (never overwritten): the report before a change is the baseline of the one after it."""
    stamp = datetime.now(UTC)
    lines = [
        f"# Eval: {name}", "", f"- date: {stamp.isoformat(timespec='seconds')}",
        f"- embedding model: {embedding_model}", f"- llm: {llm_model}", "", "| metric | score |", "|---|---|",
        *(f"| {k} | {v:.2f} |" for k, v in scores.items()), "", f"## Misses ({len(misses)})", "",
        *(f"- {m}" for m in misses), "",
    ]  # fmt: skip
    folder.mkdir(exist_ok=True)
    stem = f"{name}-{re.sub(r'[^a-z0-9]+', '-', embedding_model.lower()).strip('-')}-{stamp:%Y%m%d}"
    path = next(p for n in count(1) if not (p := folder / f"{stem}-{n}.md").exists())
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cell(text: str, limit: int = 60) -> str:
    return " ".join(text.split())[:limit].replace("|", "/")


MAX_CONCURRENCY = int(os.environ.get("EVAL_MAX_CONCURRENCY", "3"))  # free-tier model quotas are a few requests/s


def task_retry() -> "RetryConfig":
    """Rate limits and 5xx from a real model are retried with backoff instead of crashing the case."""
    from tenacity import retry_if_exception, stop_after_attempt, wait_exponential

    from app.llm.calls import is_transient

    return {
        "stop": stop_after_attempt(6),
        "wait": wait_exponential(multiplier=2, max=60),
        "retry": retry_if_exception(is_transient),
        "reraise": True,
    }


def crash_message(failures: "Sequence[ReportCaseFailure[Any, Any, Any]]") -> str:
    lines = [
        f"  {f.name}: {(f.error_message or '').splitlines()[0][:200] if f.error_message else '?'}" for f in failures
    ]
    return "\n".join([f"eval: {len(failures)} cases crashed", *lines])

"""Shared eval plumbing: settings without a database, an agent built exactly like `run_agent` builds it, results."""

import os
from dataclasses import dataclass

from pydantic import BaseModel, PostgresDsn
from pydantic_ai import Agent

from app.core.settings import Settings
from app.llm.calls import AGENT_RETRIES
from app.llm.prompts import LoadedPrompt
from app.llm.runtime import build_model


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
    settings: Settings, agent_name: str, output_type: type[T], loaded: LoadedPrompt
) -> Agent[None, T]:
    """Same model, instructions and retries as `app.llm.calls.run_agent`, minus the model_calls row."""
    model = build_model(settings, agent_name)
    return Agent(model, output_type=output_type, instructions=loaded.text, retries=AGENT_RETRIES)


def cell(text: str, limit: int = 60) -> str:
    return " ".join(text.split())[:limit].replace("|", "/")

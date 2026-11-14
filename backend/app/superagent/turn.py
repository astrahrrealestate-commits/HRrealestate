"""The research loop as the turn pipeline's `Researcher` (concierge/v7 `needs_research`).

The pipeline cannot import the loop (layering), so the workflow builds this adapter and passes it down. The system
prompt carries only the server-resolved page facts: the browser snapshot is unverified and stays out, and the loop's
own tools reach the database, messages and documents for everything else.
"""

from uuid import UUID

from sqlalchemy import Engine

from app.context.super_agent_prompt import build_super_agent_system_prompt
from app.core.settings import Settings
from app.llm.embeddings import build_embedder
from app.llm.page_blocks import PagePrompt
from app.pipeline.concierge_base import Researched, Researcher
from app.superagent.research import run_research


def make_researcher(engine: Engine, settings: Settings) -> Researcher:
    """Built for every turn but cheap: the embedder is created only when a turn actually asks for research."""

    def research(company_id: UUID, question: str, page: PagePrompt) -> Researched | None:
        system_prompt = build_super_agent_system_prompt(cases=None, query=question, page_facts=page.facts)
        embedder = build_embedder(settings)
        found = run_research(engine, settings, company_id, system_prompt, [], question, embedder=embedder)
        return None if found is None else Researched(found.answer, tuple(found.steps))

    return research

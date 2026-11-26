"""Draft research agent (M13 T8, quality tier): reads the pages found for a mail's research questions and says what
they answer, each claim tied to a numbered source and a verbatim quote.

Questions and pages are untrusted (they come from the mail and the web): they reach the model only inside escaped
`<data>` and `<document>` blocks. The `[source N, question Q]` line before each page is written by code. The agent has
no tools and gives no URLs; `app.pipeline.draft_research` maps a source number back to the page it fetched.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.contracts import PromptRef
from app.contracts.draft_research import ResearchAnswers
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_SOURCE_CHARS = 6_000


@dataclass(frozen=True)
class ResearchSource:
    question: int  # 1-based
    url: str
    title: str
    text: str


def _unchanged(output: ResearchAnswers, _loaded: LoadedPrompt) -> ResearchAnswers:
    return output


DRAFT_RESEARCH = AgentSpec(
    name="draft_research",
    prompt=PromptRef(name="draft_research", version="v1"),
    output_type=ResearchAnswers,
    finalize=_unchanged,
)


def draft_research_prompt(questions: Sequence[str], sources: Sequence[ResearchSource]) -> str:
    asked = "\n".join(f"{n}. {' '.join(q.split())}" for n, q in enumerate(questions, start=1))
    parts = [data_block("data", f"Questions:\n{asked}")]
    for n, source in enumerate(sources, start=1):
        parts.append(f"[source {n}, question {source.question}]")
        parts.append(data_block("document", f"{source.title}\n\n{source.text}".strip(), MAX_SOURCE_CHARS))
    return "\n".join(parts)

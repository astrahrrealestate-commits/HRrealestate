"""Document Q&A agent (M10): the owner's question + retrieved excerpts -> a quoted answer. No tools, no write access.

Excerpts are untrusted document text: they reach the model only inside the `excerpts` data block, and the pipeline
checks every quote against them before anything is shown.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.contracts import DocAnswer, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_EXCERPT = 3200
MAX_QUESTION_CHARS = 400


@dataclass(frozen=True)
class Passage:
    """The best matching chunk of one document: what a question is answered from."""

    document_id: UUID
    title: str
    doc_type: str
    document_date: date | None
    text: str
    rank: float


def _unchanged(output: DocAnswer, _loaded: LoadedPrompt) -> DocAnswer:
    return output


DOC_QA = AgentSpec(
    name="doc_qa", prompt=PromptRef(name="doc_qa", version="v1"), output_type=DocAnswer, finalize=_unchanged
)


def ref_of(passage: Passage) -> str:
    return passage.document_id.hex[:8]


def _entry(p: Passage) -> str:
    return (
        f"[ref {ref_of(p)}] {one_line(p.title)} ({p.doc_type}, {p.document_date or 'undated'})\n{p.text[:MAX_EXCERPT]}"
    )


def doc_qa_prompt(question: str, passages: Sequence[Passage]) -> str:
    body = "\n\n---\n\n".join(_entry(p) for p in passages) or "none"
    excerpts = data_block("excerpts", body, 4 * (MAX_EXCERPT + 200))
    return f"{excerpts}\n{data_block('message', question[:MAX_QUESTION_CHARS])}"

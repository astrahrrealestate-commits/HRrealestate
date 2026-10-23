"""Document Q&A agent (M10): the owner's question + retrieved excerpts -> a quoted answer. No tools, no write access.

Excerpts are untrusted document text: they reach the model only inside the `excerpts` data block, and the pipeline
checks every quote against them before anything is shown.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.contracts import DocAnswer, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_EXCERPT = 4800  # up to three overlapping chunks of ~1,500 characters
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
    pages: tuple[int, ...] = ()  # pages the passage spans (empty for unpaged text)
    first_ord: int = 0  # index of its first chunk: with the document it makes the passage's ref


def _unchanged(output: DocAnswer, _loaded: LoadedPrompt) -> DocAnswer:
    return output


DOC_QA = AgentSpec(
    name="doc_qa", prompt=PromptRef(name="doc_qa", version="v2"), output_type=DocAnswer, finalize=_unchanged
)


def ref_of(passage: Passage) -> str:
    """8 hex characters of a hash of the whole document id and the passage's first chunk. Document ids are UUIDv7
    (their first bytes are a timestamp), so a prefix would collide for documents created together."""
    digest = hashlib.sha1(f"{passage.document_id}:{passage.first_ord}".encode(), usedforsecurity=False)
    return digest.hexdigest()[:8]


def pages_label(pages: Sequence[int]) -> str:
    if not pages:
        return ""
    return f", p.{pages[0]}" if len(pages) == 1 else f", p.{pages[0]}-{pages[-1]}"


def entry_text(p: Passage) -> str:
    """One excerpt as the model sees it: ref, title, type, date, pages, then the text."""
    head = f"[ref {ref_of(p)}] {one_line(p.title)} ({p.doc_type}, {p.document_date or 'undated'}{pages_label(p.pages)})"
    return f"{head}\n{p.text[:MAX_EXCERPT]}"


def doc_qa_prompt(question: str, passages: Sequence[Passage]) -> str:
    body = "\n\n---\n\n".join(entry_text(p) for p in passages) or "none"
    excerpts = data_block("excerpts", body, max(4, len(passages)) * (MAX_EXCERPT + 200))
    return f"{excerpts}\n{data_block('message', question[:MAX_QUESTION_CHARS])}"

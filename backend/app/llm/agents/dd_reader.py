"""Due-diligence reader agent: one property document's text -> `DDDocRead` (kind, quoted claims, quoted flags).

The text is untrusted data (invariant 6): it reaches the model only inside the `document` block. The agent has no
tools and rates nothing; the pipeline checks every quote against the text and the engine does all comparing.
"""

from app.contracts import PromptRef
from app.contracts.diligence import DDDocRead
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_DOCUMENT_CHARS = 24_000
READER_VERSION = "dd_reader/v1"  # the cache key of a stored read: a new prompt version means new reads


def _unchanged(output: DDDocRead, _loaded: LoadedPrompt) -> DDDocRead:
    return output


DD_READER = AgentSpec(
    name="dd_reader",
    prompt=PromptRef(name="dd_reader", version="v1"),
    output_type=DDDocRead,
    finalize=_unchanged,
    gemini_prompted=True,
)


def dd_reader_prompt(filename: str | None, document_text: str) -> str:
    meta = f"filename: {one_line(filename or 'unnamed')}"
    body = document_text.strip() or "none"
    return "\n".join([data_block("file", meta), data_block("document", body, MAX_DOCUMENT_CHARS)])

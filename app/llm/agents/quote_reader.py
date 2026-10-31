"""Quote reader agent (M11): vendor quote text -> ExtractedQuote. Vendor text is untrusted data (invariant 6).

The agent only extracts what the text states; the review engine, not the model, judges the prices. A lump sum is
`total` set with `lines=[]`. `received_on` is the message date from our DB, so relative dates resolve.
"""

from collections.abc import Sequence
from datetime import date

from app.contracts import ExtractedQuote, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import MAX_ATTACHMENTS, data_block, one_line

MAX_DOCUMENT_CHARS = 24_000


def _unchanged(output: ExtractedQuote, _loaded: LoadedPrompt) -> ExtractedQuote:
    return output


QUOTE_READER = AgentSpec(
    name="quote_reader",
    prompt=PromptRef(name="quote_reader", version="v1"),
    output_type=ExtractedQuote,
    finalize=_unchanged,
)


def quote_reader_prompt(subject: str | None, text: str, attachment_texts: Sequence[str], received_on: date) -> str:
    head = data_block("data", f"Subject: {one_line(subject or '') or 'none'}")
    body = data_block("message", text.strip() or "none")
    attachments = [data_block("document", t.strip() or "none", MAX_DOCUMENT_CHARS) for t in attachment_texts]
    return "\n".join(
        [f"<received_on>{received_on.isoformat()}</received_on>", head, body, *attachments[:MAX_ATTACHMENTS]]
    )

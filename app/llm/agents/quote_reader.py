"""Quote reader agent (M11): vendor quote text -> ExtractedQuote. Vendor text is untrusted data (invariant 6).

The agent only extracts what the text states; the review engine, not the model, judges the prices. A lump sum is
`total` set with `lines=[]`. `received_on` is the message date from our DB, so relative dates resolve.
"""

import re
from collections.abc import Sequence
from datetime import date

from app.contracts import ExtractedQuote, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import MAX_ATTACHMENTS, MAX_BODY_CHARS, RAW_FACTOR, data_block, normalise, one_line

MAX_DOCUMENT_CHARS = 24_000
_RECEIVED_ON_TAG = re.compile(r"<(\s*/?\s*)(received_on)\b", re.IGNORECASE)


def _unchanged(output: ExtractedQuote, _loaded: LoadedPrompt) -> ExtractedQuote:
    return output


QUOTE_READER = AgentSpec(
    name="quote_reader",
    prompt=PromptRef(name="quote_reader", version="v1"),
    output_type=ExtractedQuote,
    finalize=_unchanged,
)


def _untrusted(content: str, limit: int = MAX_BODY_CHARS) -> str:
    """Vendor text with the trusted `<received_on>` tag (open or close) neutralised, so it cannot forge the date line.
    `received_on` is not a shared block tag, so `data_block` would leave it alone. Normalising first catches the same
    look-alikes `escape` does; `data_block` normalising again changes nothing."""
    return _RECEIVED_ON_TAG.sub(lambda m: "<\\" + m.group(1) + m.group(2), normalise(content[: RAW_FACTOR * limit]))


def quote_reader_prompt(subject: str | None, text: str, attachment_texts: Sequence[str], received_on: date) -> str:
    head = data_block("data", f"Subject: {_untrusted(one_line(subject or '')) or 'none'}")
    body = data_block("message", _untrusted(text.strip()) or "none")
    attachments = [
        data_block("document", _untrusted(t.strip(), MAX_DOCUMENT_CHARS) or "none", MAX_DOCUMENT_CHARS)
        for t in attachment_texts
    ]
    date_line = f"<received_on>{received_on.isoformat()}</received_on>"
    return "\n".join([date_line, head, body, *attachments[:MAX_ATTACHMENTS]])

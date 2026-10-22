"""Document reader agent (M10): extracted text + metadata -> DocumentFacts. Text is untrusted data (invariant 6).

`doc_classifier` (metadata only) still runs first and decides whether a document may be read at all: ID documents
never reach this agent (ADR 0007).
"""

from app.contracts import DocumentFacts, ExtractedText, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_DOCUMENT_CHARS = 24_000
MAX_MESSAGE_CHARS = 4000
MAX_CASE_CHARS = 1200


def _facts(output: DocumentFacts, _loaded: LoadedPrompt) -> DocumentFacts:
    return output


def _text(output: ExtractedText, _loaded: LoadedPrompt) -> ExtractedText:
    return output


DOC_READER = AgentSpec(
    name="doc_reader", prompt=PromptRef(name="doc_reader", version="v1"), output_type=DocumentFacts, finalize=_facts
)
DOC_OCR = AgentSpec(
    name="doc_ocr",
    prompt=PromptRef(name="doc_ocr", version="v1"),
    output_type=ExtractedText,
    finalize=_text,
    redact_output=True,  # the text is kept on the attachment (and purged for identity documents), not in model_calls
)


def doc_reader_prompt(
    filename: str | None,
    mime_type: str,
    size_bytes: int,
    sender: str,
    message_text: str,
    case_summary: str | None,
    document_text: str,
) -> str:
    meta = "\n".join(
        [
            f"filename: {one_line(filename or 'unnamed')}",
            f"mime_type: {one_line(mime_type)}",
            f"size_bytes: {size_bytes}",
            f"sender: {one_line(sender) or 'unknown'}",
        ]
    )
    message = message_text.strip()[:MAX_MESSAGE_CHARS] or "none"
    case = (case_summary or "").strip()[:MAX_CASE_CHARS] or "none"
    body = document_text.strip() or "none"
    return "\n".join(
        [
            data_block("file", meta),
            data_block("message", message),
            data_block("case", case),
            data_block("document", body, MAX_DOCUMENT_CHARS),
        ]
    )

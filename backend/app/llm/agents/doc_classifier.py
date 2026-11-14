"""Document classifier agent (#9): document type, title and date for filing.

Metadata only (user decision): the file name, type, size and sender, the text of the message it came with and the
case summary. The file's contents are never read or sent to the model.
"""

from app.contracts import DocumentClassification, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, one_line

MAX_MESSAGE_CHARS = 4000
MAX_CASE_CHARS = 1200


def _unchanged(output: DocumentClassification, _loaded: LoadedPrompt) -> DocumentClassification:
    return output


DOC_CLASSIFIER = AgentSpec(
    name="doc_classifier",
    prompt=PromptRef(name="doc_classifier", version="v1"),
    output_type=DocumentClassification,
    finalize=_unchanged,
    thinking=False,
)


def doc_classifier_prompt(
    filename: str | None, mime_type: str, size_bytes: int, sender: str, message_text: str, case_summary: str | None
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
    return "\n".join([data_block("file", meta), data_block("message", message), data_block("case", case)])

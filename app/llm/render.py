"""Rendering prompt data blocks safely (delimiters, escaping, truncation)."""

from collections.abc import Sequence
from dataclasses import dataclass

MAX_BODY_CHARS = 8000


@dataclass(frozen=True)
class AttachmentMeta:
    filename: str | None
    mime_type: str
    size_bytes: int


def escape(content: str, tag: str) -> str:
    """Untrusted text can never close its data block."""
    return content.replace(f"</{tag}", f"<\\/{tag}")


def data_block(tag: str, content: str) -> str:
    """Renders content inside <tag>...</tag>, truncating and escaping closing tags."""
    if len(content) > MAX_BODY_CHARS:
        content = content[:MAX_BODY_CHARS] + "\n[…truncated]"
    return f"<{tag}>\n{escape(content, tag)}\n</{tag}>"


def _one_line(value: str) -> str:
    return " ".join(value.split())[:200]


def attachments_block(items: Sequence[AttachmentMeta]) -> str:
    """Renders attachments metadata list inside <attachments>...</attachments>."""
    if not items:
        return "<attachments>\nnone\n</attachments>"
    lines = [
        escape(
            f"- {_one_line(item.filename or 'unnamed')} ({_one_line(item.mime_type)}, {item.size_bytes} bytes)",
            "attachments",
        )
        for item in items
    ]
    return "<attachments>\n" + "\n".join(lines) + "\n</attachments>"

"""Rendering prompt data blocks safely (delimiters, escaping, truncation)."""

from collections.abc import Sequence
from dataclasses import dataclass

MAX_BODY_CHARS = 8000


@dataclass(frozen=True)
class AttachmentMeta:
    filename: str | None
    mime_type: str
    size_bytes: int


def data_block(tag: str, content: str) -> str:
    """Renders content inside <tag>...</tag>, truncating and escaping closing tags."""
    if len(content) > MAX_BODY_CHARS:
        content = content[:MAX_BODY_CHARS] + "\n[…truncated]"
    escaped = content.replace(f"</{tag}", f"<\\/{tag}")
    return f"<{tag}>\n{escaped}\n</{tag}>"


def attachments_block(items: Sequence[AttachmentMeta]) -> str:
    """Renders attachments metadata list inside <attachments>...</attachments>."""
    if not items:
        return "<attachments>\nnone\n</attachments>"
    lines = [f"- {item.filename or 'unnamed'} ({item.mime_type}, {item.size_bytes} bytes)" for item in items]
    return "<attachments>\n" + "\n".join(lines) + "\n</attachments>"

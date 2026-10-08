"""Rendering prompt data blocks safely (delimiters, escaping, truncation).

Untrusted text (messages, subjects, file names, case summaries, contractor names) only ever reaches a model inside
a block rendered here (CLAUDE.md invariant 6). Inside such text, every block tag, opening or closing, of ANY block
type is neutralised, so content can neither close its own block nor fake another one. Look-alike characters are
normalised first: fullwidth and small-form angle brackets become plain ones, and zero-width characters are removed,
so `＜/message＞` or `</mes​sage>` are caught like `</message>`.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

MAX_BODY_CHARS = 8000
MAX_ATTACHMENTS = 10
BLOCK_TAGS = ("message", "data", "waiting", "contractors", "attachments", "file", "case")

_LOOKALIKES = str.maketrans({"＜": "<", "＞": ">", "﹤": "<", "﹥": ">"})
_ZERO_WIDTH = re.compile("[​‌‍⁠﻿]")
_TAG = re.compile(rf"<(\s*/?\s*)({'|'.join(BLOCK_TAGS)})\b", re.IGNORECASE)


@dataclass(frozen=True)
class AttachmentMeta:
    filename: str | None
    mime_type: str
    size_bytes: int


def _normalise(content: str) -> str:
    return _ZERO_WIDTH.sub("", content.translate(_LOOKALIKES))


def escape(content: str, tag: str | None = None) -> str:
    """Neutralise every block tag (any type, opening or closing, any case or spacing) inside untrusted text.

    `tag` is accepted for call-site readability; all block tags are escaped regardless, in one pass.
    """
    return _TAG.sub(lambda m: "<\\" + m.group(1) + m.group(2), _normalise(content))


def data_block(tag: str, content: str) -> str:
    """Renders content inside <tag>...</tag>, truncating and escaping every block tag inside it."""
    if len(content) > MAX_BODY_CHARS:
        content = content[:MAX_BODY_CHARS] + "\n[…truncated]"
    return f"<{tag}>\n{escape(content, tag)}\n</{tag}>"


def one_line(value: str) -> str:
    return " ".join(value.split())[:200]


def attachments_block(items: Sequence[AttachmentMeta]) -> str:
    """Attachment metadata inside <attachments>...</attachments>, at most MAX_ATTACHMENTS lines plus "+N more"."""
    if not items:
        return "<attachments>\nnone\n</attachments>"
    lines = [
        escape(f"- {one_line(item.filename or 'unnamed')} ({one_line(item.mime_type)}, {item.size_bytes} bytes)")
        for item in items[:MAX_ATTACHMENTS]
    ]
    if len(items) > MAX_ATTACHMENTS:
        lines.append(f"+{len(items) - MAX_ATTACHMENTS} more")
    return "<attachments>\n" + "\n".join(lines) + "\n</attachments>"

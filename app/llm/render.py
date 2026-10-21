"""Rendering prompt data blocks safely (delimiters, escaping, truncation).

Untrusted text (messages, subjects, file names, case summaries, contractor names) only ever reaches a model inside
a block rendered here (CLAUDE.md invariant 6). Inside such text, every block tag, opening or closing, of ANY block
type is neutralised, so content can neither close its own block nor fake another one. Look-alike characters are
normalised first: format characters (Unicode category Cf: zero-width, soft hyphen, bidi controls) are removed, the
text is NFKC-normalised (fullwidth and small-form brackets, solidus and letters become plain ones), and angle
quotation marks and other angle brackets or slashes become `<`, `>` and `/`. So `＜/message＞`, `‹/message›`,
`</mes` ZWSP `sage>` or `</page` soft-hyphen `_snapshot>` are caught like `</message>`. NFKC also folds compatibility
characters in ordinary text (`½` becomes `1/2`, `ﬁ` becomes `fi`, a no-break space a space); the meaning is kept.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

MAX_BODY_CHARS = 8000
MAX_ATTACHMENTS = 10
BLOCK_TAGS = (
    "message", "data", "waiting", "contractors", "attachments", "file", "case", "mode", "history", "page_facts",
    "page_snapshot",
)  # fmt: skip

# Applied after NFKC: fullwidth and small forms are already plain there, and U+2329/U+232A became U+3008/U+3009.
_LOOKALIKES = str.maketrans(
    {
        "\u2039": "<", "\u203a": ">", "\u3008": "<", "\u3009": ">", "\u27e8": "<", "\u27e9": ">",
        "\u2044": "/", "\u2215": "/", "\u29f8": "/",
    }
)  # fmt: skip
_TAG = re.compile(rf"<(\s*/?\s*)({'|'.join(BLOCK_TAGS)})\b", re.IGNORECASE)


@dataclass(frozen=True)
class AttachmentMeta:
    filename: str | None
    mime_type: str
    size_bytes: int


def _normalise(content: str) -> str:
    visible = "".join(ch for ch in content if unicodedata.category(ch) != "Cf")
    return unicodedata.normalize("NFKC", visible).translate(_LOOKALIKES)


def escape(content: str, tag: str | None = None) -> str:
    """Neutralise every block tag (any type, opening or closing, any case or spacing) inside untrusted text.

    `tag` is accepted for call-site readability; all block tags are escaped regardless, in one pass.
    """
    return _TAG.sub(lambda m: "<\\" + m.group(1) + m.group(2), _normalise(content))


def data_block(tag: str, content: str) -> str:
    """Renders content inside <tag>...</tag>, truncating and escaping every block tag inside it."""
    marker = "\n[…truncated]" if len(content) > MAX_BODY_CHARS else ""
    return f"<{tag}>\n{escape(content[:MAX_BODY_CHARS], tag)}{marker}\n</{tag}>"


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

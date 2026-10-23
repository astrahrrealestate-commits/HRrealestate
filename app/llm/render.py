"""Rendering prompt data blocks safely (delimiters, escaping, truncation).

Untrusted text (messages, subjects, file names, case summaries, contractor names) only ever reaches a model inside
a block rendered here (CLAUDE.md invariant 6). Inside such text, every block tag, opening or closing, of ANY block
type is neutralised, so content can neither close its own block nor fake another one. Look-alike characters are
normalised first: format characters (Unicode category Cf: zero-width, soft hyphen, bidi controls) and the other
default-ignorable code points (combining grapheme joiner, variation selectors, Hangul fillers) are removed, the
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
RAW_FACTOR = 4  # raw input read per capped character, before normalising (format characters are dropped there)
MAX_ATTACHMENTS = 10
BLOCK_TAGS = (
    "message", "data", "waiting", "contractors", "attachments", "file", "case", "mode", "history", "page_facts",
    "page_snapshot", "owner_guidance", "current_draft", "document", "excerpts",
)  # fmt: skip

# Applied after NFKC: fullwidth and small forms are already plain there, and U+2329/U+232A became U+3008/U+3009.
_LOOKALIKES = str.maketrans(
    {
        "\u2039": "<", "\u203a": ">", "\u3008": "<", "\u3009": ">", "\u27e8": "<", "\u27e9": ">",
        "\u2044": "/", "\u2215": "/", "\u29f8": "/",
    }
)  # fmt: skip
# Unicode Default_Ignorable_Code_Point (explicit table; most are also category Cf, the rest are Mn/Lo fillers such as
# the combining grapheme joiner, variation selectors and Hangul fillers).
_IGNORABLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f"
    "\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufff8\U0001bca0-\U0001bca3\U0001d173-\U0001d17a"
    "\U000e0000-\U000e0fff]"
)
_TAG = re.compile(rf"<(\s*/?\s*)({'|'.join(BLOCK_TAGS)})\b", re.IGNORECASE)


@dataclass(frozen=True)
class AttachmentMeta:
    filename: str | None
    mime_type: str
    size_bytes: int


def _strip_invisible(text: str) -> str:
    return _IGNORABLE.sub("", "".join(ch for ch in text if unicodedata.category(ch) != "Cf"))


def _normalise(content: str) -> str:
    """Invisible characters out (again after NFKC: U+3164/U+FFA0 become U+1160), compatibility forms folded,
    angle look-alikes mapped."""
    return _strip_invisible(unicodedata.normalize("NFKC", _strip_invisible(content))).translate(_LOOKALIKES)


def normalise(content: str) -> str:
    """The normalisation `data_block` applies before capping, for callers that budget text before rendering it
    (re-applying it never makes text longer)."""
    return _normalise(content)


def escape(content: str, tag: str | None = None) -> str:
    """Neutralise every block tag (any type, opening or closing, any case or spacing) inside untrusted text.

    `tag` is accepted for call-site readability; all block tags are escaped regardless, in one pass.
    """
    return _TAG.sub(lambda m: "<\\" + m.group(1) + m.group(2), _normalise(content))


def data_block(tag: str, content: str, limit: int = MAX_BODY_CHARS) -> str:
    """Renders content inside <tag>...</tag>, truncating and escaping every block tag inside it. The cap applies
    after normalisation (NFKC can expand a character up to 18-fold); raw input is bounded first. Escaping runs after
    truncation, so a cut tag is never left half-escaped. `limit` is `MAX_BODY_CHARS` for every block except
    `<page_facts>` (`page_blocks.MAX_PAGE_FACTS`)."""
    raw_cap = RAW_FACTOR * limit
    text = _normalise(content[:raw_cap])
    truncated = len(content) > raw_cap or len(text) > limit
    marker = "\n[…truncated]" if truncated else ""
    return f"<{tag}>\n{escape(text[:limit], tag)}{marker}\n</{tag}>"


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

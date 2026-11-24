"""RFC 822 parsing for inbound email (stdlib `email` does the MIME work). `parse_email` never raises.

- Body: text/plain preferred, else HTML→text (inscriptis); extra inline text parts (Apple Mail split layout) are
  appended; forwarded `message/rfc822` parts become an `.eml` attachment plus a quoted "Forwarded message" block.
- Quote stripping (mail-parser-reply, de+en) only for replies without forward markers, on bounded input; the full
  text is always kept in `full_text`.
- Hostile input is bounded: nesting depth, part count, attachment count/bytes, text length. All strings are cleaned
  (no NUL/C0 controls, no lone surrogates; header-derived values are single-line).
"""

import mimetypes
import re
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser, BytesParser

from inscriptis import get_text
from mailparser_reply import EmailReplyParser

from app.channels.gmail.forward import FORWARD_MARKERS, origin_from_text
from app.channels.gmail.parsed import ParsedAttachment, ParsedEmail
from app.channels.text_clean import clean_filename, clean_header, clean_mime, clean_text
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_DEPTH = 24
MAX_PARTS = 400
MAX_ATTACHMENTS = 50
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 60 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
QUOTE_STRIP_MAX_CHARS = 32_000  # worst case ~0.15 s per mail; longer texts stay unstripped
QUOTE_STRIP_MAX_LINE = 500  # reply headers are short; long lines make the reply parser quadratic
MAX_REFERENCES_CHARS = 16_000

_REPLY_PARSER = EmailReplyParser(languages=["nl", "de", "en"])
_CID_REF = re.compile(r"cid:([^\"'\s>)]+)", re.IGNORECASE)
_REPLY_SUBJECT = re.compile(r"^\s*(re|aw|antw|sv|vs)\s*:", re.IGNORECASE)


# ---- traversal ---------------------------------------------------------------------------------------------------


@dataclass
class _Part:
    part: EmailMessage
    parent_type: str | None


def _flatten(msg: EmailMessage, skipped: list[str]) -> list[_Part]:
    """Leaf parts (incl. message/rfc822 as a leaf), iterative, bounded by depth and count."""
    leaves: list[_Part] = []
    stack: list[tuple[EmailMessage, str | None, int]] = [(msg, None, 0)]
    seen = 0
    while stack:
        part, parent_type, depth = stack.pop()
        seen += 1
        if seen > MAX_PARTS:
            skipped.append(f"parts beyond {MAX_PARTS}")
            break
        if part.is_multipart() and part.get_content_type() != "message/rfc822":
            if depth >= MAX_DEPTH:
                skipped.append(f"nesting beyond depth {MAX_DEPTH}")
                continue
            children = [p for p in part.iter_parts() if isinstance(p, EmailMessage)]
            stack.extend((child, part.get_content_type(), depth + 1) for child in reversed(children))
        else:
            leaves.append(_Part(part, parent_type))
    return leaves


def _decoded(part: EmailMessage) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except Exception as exc:  # bad charset/encoding: fall back to raw bytes
        log.info("email.part_decode_fallback", error_type=type(exc).__name__)
    payload = part.get_payload(decode=True)
    return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


def _is_attachment(part: EmailMessage) -> bool:
    return part.get_content_disposition() == "attachment" or bool(part.get_filename())


def _as_text(part: EmailMessage) -> str:
    text = _decoded(part)
    if part.get_content_subtype() == "html":
        text = get_text(text)
    return "\n".join(line.rstrip() for line in clean_text(text).split("\n")).strip()


# ---- headers -----------------------------------------------------------------------------------------------------


def _header(msg: EmailMessage, name: str, limit: int = 998) -> str | None:
    try:
        value = msg[name]
    except Exception:  # malformed header
        return None
    return clean_header(str(value), limit) if value is not None else None


def _addresses(msg: EmailMessage, name: str) -> list[tuple[str, str]]:
    try:
        header = msg[name]
        addresses = header.addresses if header is not None else ()
    except Exception:
        return []
    out = []
    for a in addresses:
        spec = clean_header(a.addr_spec) or ""
        if "@" in spec:
            out.append((spec.lower(), clean_header(a.display_name) or ""))
    return out


# ---- body + attachments ------------------------------------------------------------------------------------------


def _forwarded_block(container: EmailMessage) -> tuple[str, bytes]:
    inner = container.get_payload(0) if container.is_multipart() else None
    if not isinstance(inner, EmailMessage):
        return "", b""
    body = inner.get_body(preferencelist=("plain", "html"))
    text = _as_text(body) if isinstance(body, EmailMessage) else ""
    header = f"From: {_header(inner, 'From') or '?'}\nSubject: {_header(inner, 'Subject') or ''}"
    return f"---------- Forwarded message ----------\n{header}\n\n{text}".strip(), inner.as_bytes()


def _attached_origin(leaves: list[_Part]) -> tuple[str, str | None] | None:
    """Original sender of an attached `message/rfc822` (its From header)."""
    for leaf in leaves:
        if clean_mime(leaf.part.get_content_type()) != "message/rfc822" or not leaf.part.is_multipart():
            continue
        inner = leaf.part.get_payload(0)
        origin = _addresses(inner, "From") if isinstance(inner, EmailMessage) else []
        if origin:
            return origin[0][0], origin[0][1] or None
    return None


def _referenced_cids(leaves: list[_Part]) -> set[str]:
    cids: set[str] = set()
    for leaf in leaves:
        if leaf.part.get_content_type() == "text/html" and not _is_attachment(leaf.part):
            cids.update(m.lower() for m in _CID_REF.findall(_decoded(leaf.part)))
    return cids


@dataclass
class _Budget:
    skipped: list[str]
    total: int = 0
    count: int = 0

    def admit(self, label: str, size: int) -> bool:
        if self.count >= MAX_ATTACHMENTS or size > MAX_ATTACHMENT_BYTES:
            self.skipped.append(f"attachment {label} ({size} bytes)")
            return False
        if self.total + size > MAX_TOTAL_ATTACHMENT_BYTES:
            self.skipped.append(f"attachment {label} (total size limit)")
            return False
        self.total, self.count = self.total + size, self.count + 1
        return True


def _payload(part: EmailMessage) -> bytes:
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _classify(leaf: _Part, index: int, extra_text: list[str]) -> tuple[str | None, str, bytes] | None:
    """(filename, mime type, data) for an attachment; None for body text (appended) or an alternative."""
    part, ctype = leaf.part, clean_mime(leaf.part.get_content_type())
    if ctype == "message/rfc822":
        text, data = _forwarded_block(part)
        if text:
            extra_text.append(text)
        return "forwarded.eml", ctype, data
    if part.get_content_maintype() == "text" and not _is_attachment(part):
        if leaf.parent_type == "multipart/alternative" or ctype == "text/html":
            return None
        if ctype == "text/plain":
            extra_text.append(_as_text(part))
            return None
        return f"part-{index}{mimetypes.guess_extension(ctype) or '.txt'}", ctype, _payload(part)
    return clean_filename(part.get_filename()), ctype, _payload(part)


def _collect(
    leaves: list[_Part], body: EmailMessage | None, skipped: list[str]
) -> tuple[list[str], list[ParsedAttachment]]:
    extra_text: list[str] = []
    attachments: list[ParsedAttachment] = []
    referenced = _referenced_cids(leaves)
    budget = _Budget(skipped)
    for index, leaf in enumerate(leaves):
        if leaf.part is body or (found := _classify(leaf, index, extra_text)) is None:
            continue
        filename, mime, data = found
        if not budget.admit(filename or mime, len(data)):
            continue
        content_id = (_header(leaf.part, "Content-ID") or "").strip("<>") or None
        inline = content_id is not None and content_id.lower() in referenced
        attachments.append(ParsedAttachment(filename, mime, data, inline=inline, content_id=content_id))
    return extra_text, attachments


def _strip_quotes(text: str, *, is_reply: bool) -> tuple[str, bool]:
    too_big = len(text) > QUOTE_STRIP_MAX_CHARS or any(len(line) > QUOTE_STRIP_MAX_LINE for line in text.split("\n"))
    if not text or not is_reply or too_big or FORWARD_MARKERS.search(text):
        return text, False
    try:
        reply = _REPLY_PARSER.parse_reply(text=re.sub(r"[ \t]{2,}", " ", text)).rstrip()
    except Exception:
        log.warning("email.reply_parser_failed")
        return text, False
    changed = reply.strip() and reply.strip() != text.rstrip().strip()
    return (reply.strip(), True) if changed else (text, False)


def _choose_body(msg: EmailMessage, leaves: list[_Part]) -> EmailMessage | None:
    """text/plain preferred; an empty plain part falls back to its HTML alternative."""
    for preference in (("plain", "html"), ("html",)):
        body = msg.get_body(preferencelist=preference)
        if isinstance(body, EmailMessage) and any(leaf.part is body for leaf in leaves) and _as_text(body):
            return body
    return None


def _cap(text: str) -> str:
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + "\n[… truncated]"


def _parse(raw: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    skipped: list[str] = []
    leaves = _flatten(msg, skipped)
    body = _choose_body(msg, leaves)
    extra_text, attachments = _collect(leaves, body, skipped)
    full_text = "\n\n".join(t for t in [_as_text(body) if body else "", *extra_text] if t).strip()
    subject = _header(msg, "Subject") or ""
    in_reply_to = _header(msg, "In-Reply-To", MAX_REFERENCES_CHARS)
    references = _header(msg, "References", MAX_REFERENCES_CHARS)
    is_reply = bool(in_reply_to or references or _REPLY_SUBJECT.match(subject))
    text, stripped = _strip_quotes(full_text, is_reply=is_reply)
    sender = _addresses(msg, "From")
    origin = _attached_origin(leaves) or origin_from_text(full_text)
    return ParsedEmail(
        from_addr=sender[0][0] if sender else None,
        from_name=(sender[0][1] or None) if sender else None,
        forwarded_from=origin[0] if origin else None,
        forwarded_from_name=origin[1] if origin else None,
        to=[a for a, _ in _addresses(msg, "To")],
        cc=[a for a, _ in _addresses(msg, "Cc")],
        subject=subject,
        message_id=_header(msg, "Message-ID"),
        in_reply_to=in_reply_to,
        references=references,
        text=_cap(text),
        full_text=_cap(full_text),
        quote_stripped=stripped,
        attachments=attachments,
        skipped=skipped,
    )


def _headers_only(raw: bytes) -> ParsedEmail:
    """Degraded result that keeps the sender, so a hostile body cannot make the message unroutable."""
    try:
        headers = BytesHeaderParser(policy=policy.default).parsebytes(raw)
        sender = _addresses(headers, "From")
        subject = _header(headers, "Subject") or ""
    except Exception:  # headers themselves unreadable
        sender, subject = [], ""
    return ParsedEmail(
        from_addr=sender[0][0] if sender else None,
        from_name=(sender[0][1] or None) if sender else None,
        subject=subject,
        text="[unparseable email]",
        parse_error=True,
    )


def parse_email(raw: bytes) -> ParsedEmail:
    """Never raises: hostile or broken mail degrades to a placeholder instead of failing ingestion forever."""
    try:
        return _parse(raw)
    except Exception as exc:  # RecursionError, HeaderParseError and other parser failures
        log.warning("email.unparseable", error_type=type(exc).__name__, size=len(raw))
        return _headers_only(raw)

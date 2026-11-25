"""Chunking and conversation formatting logic for Message RAG."""

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.context.shown_sender import shown_sender_name
from app.contracts import Channel, Direction
from app.db.models import MessageRow

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")
_LINE_SYNTAX = re.compile(r"[\[\]|()<>]")
_BODY_SYNTAX = str.maketrans("[]|", "()/")  # a body cannot write a line head of its own
LINE_HEAD = re.compile(r"^\[[^\]\n]*\] ")
MAX_CHUNK_CHARS = 2400  # ~600 tokens
TARGET_CHUNK_CHARS = 1600  # ~400 tokens
MAX_GAP = timedelta(hours=6)


def _inbound_label(msg: MessageRow, person_name: str | None) -> str:
    """The sender slot of a chunk line. An email's header name is chosen by its sender, so it cannot carry the line's
    own delimiters or the owner label, and the address always stands beside it."""
    name = " ".join(_LINE_SYNTAX.sub(" ", shown_sender_name(msg, person_name)).split())
    if msg.channel is Channel.gmail and msg.sender_identity and name != msg.sender_identity:
        return f"{name} <{msg.sender_identity}>"
    return name


def format_message_line(msg: MessageRow, person_name: str | None = None) -> str:
    """Formats a single message with an Amsterdam timestamp and sender attribution."""
    local_dt = msg.sent_at.astimezone(AMSTERDAM_TZ)
    stamp = local_dt.strftime("%Y-%m-%d %H:%M")

    dir_str = msg.direction.value if hasattr(msg.direction, "value") else str(msg.direction)
    is_outbound = dir_str == Direction.outbound.value

    sender = "Harjot (Owner)" if is_outbound else _inbound_label(msg, person_name)

    # Clean multi-line whitespace
    clean_text = " ".join(msg.text.split()) if msg.text else "(no text)"
    return f"[{stamp} | {sender} | {dir_str}] {plain_body(clean_text)}"


def plain_body(text: str) -> str:
    return text.translate(_BODY_SYNTAX)


def format_context_header(
    channel: str,
    thread_ref: str,
    subject: str | None = None,
    person_name: str | None = None,
    unit_address: str | None = None,
    case_summary: str | None = None,
) -> str:
    """Builds the searchable context header prepended to the chunk."""
    parts: list[str] = []
    if subject:
        parts.append(f"Subject: {subject}")
    parts.append(f"Channel: {channel} | Thread: {thread_ref}")
    if person_name:
        parts.append(f"Tenant: {person_name}")
    if unit_address:
        parts.append(f"Property: {unit_address}")
    if case_summary:
        parts.append(f"Case Context: {case_summary}")
    return " | ".join(parts)


def compute_content_hash(context: str | None, text: str) -> str:
    """Computes a sha256 fingerprint of the chunk contents to avoid redundant re-embeddings."""
    payload = f"{context or ''}\n{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def should_start_new_chunk(
    current_text_len: int,
    additional_text_len: int,
    last_sent_at: datetime,
    new_sent_at: datetime,
    is_open: bool,
) -> bool:
    """Decides if adding this message requires closing the current chunk and opening a new one."""
    if not is_open:
        return True
    if (new_sent_at - last_sent_at) > MAX_GAP:
        return True
    return (current_text_len + additional_text_len) > MAX_CHUNK_CHARS

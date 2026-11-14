"""Chunking and conversation formatting logic for Message RAG."""

import hashlib
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.contracts import Direction
from app.db.models import MessageRow

AMSTERDAM_TZ = ZoneInfo("Europe/Amsterdam")
MAX_CHUNK_CHARS = 2400  # ~600 tokens
TARGET_CHUNK_CHARS = 1600  # ~400 tokens
MAX_GAP = timedelta(hours=6)


def format_message_line(msg: MessageRow, person_name: str | None = None) -> str:
    """Formats a single message with an Amsterdam timestamp and sender attribution."""
    local_dt = msg.sent_at.astimezone(AMSTERDAM_TZ)
    stamp = local_dt.strftime("%Y-%m-%d %H:%M")

    dir_str = msg.direction.value if hasattr(msg.direction, "value") else str(msg.direction)
    is_outbound = dir_str == Direction.outbound.value

    if is_outbound:
        sender = "Harjot (Owner)"
    else:
        meta: dict[str, Any] = msg.meta or {}
        sender = person_name or meta.get("from_name") or meta.get("contact_name") or msg.sender_identity or "Tenant"

    # Clean multi-line whitespace
    clean_text = " ".join(msg.text.split()) if msg.text else "[no text]"
    return f"[{stamp} | {sender} | {dir_str}] {clean_text}"


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

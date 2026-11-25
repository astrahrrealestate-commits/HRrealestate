"""Gatekeeper rules for Message RAG indexing.

Evaluates fast Python checks to skip junk, spam, reactions, and automated newsletters
without making expensive embedding calls.
"""

from typing import Any

from app.db.enums import PipelineStatus
from app.db.models import MessageRow, UnderstandingRow

IGNORED_GMAIL_LABELS = frozenset(
    {
        "CATEGORY_PROMOTIONS",
        "CATEGORY_SOCIAL",
        "SPAM",
        "TRASH",
    }
)

BOUNCE_SENDER_MARKERS = frozenset(
    {
        "mailer-daemon",
        "postmaster",
    }
)

BOUNCE_SUBJECT_MARKERS = (
    "delivery status notification (failure)",
    "undeliverable:",
    "failure notice",
)


def should_index_message(
    msg: MessageRow,
    understanding: UnderstandingRow | None = None,
) -> tuple[bool, str | None]:
    """Determines whether a message should be indexed into Message RAG.

    Returns:
        (True, None) if the message should be chunked and embedded.
        (False, reason_string) if the message is skipped.
    """
    channel_str = msg.channel.value if hasattr(msg.channel, "value") else str(msg.channel)
    if channel_str not in ("whatsapp", "gmail", "google_chat", "dashboard"):
        return False, f"unsupported_channel:{channel_str}"

    # 1. Spam check via Understanding Agent
    if understanding is not None:
        cat = understanding.category.value if hasattr(understanding.category, "value") else str(understanding.category)
        if cat == "spam":
            return False, "spam_category"

    if msg.pipeline_status is PipelineStatus.skipped:  # a chat the owner keeps only in Chats (ADR 0015)
        return False, "chat_only"

    meta: dict[str, Any] = msg.meta or {}

    # 2. Gmail-specific gate rules
    if channel_str == "gmail":
        labels = meta.get("labels") or []
        if any(label in IGNORED_GMAIL_LABELS for label in labels):
            return False, "promotional_or_spam_label"

        from_addr = (meta.get("from") or msg.sender_identity or "").lower()
        if any(marker in from_addr for marker in BOUNCE_SENDER_MARKERS):
            return False, "mailer_daemon_bounce"

        subject = (meta.get("subject") or "").lower()
        if any(subject.startswith(prefix) for prefix in BOUNCE_SUBJECT_MARKERS):
            return False, "bounce_notification"

    # 3. WhatsApp-specific gate rules
    if channel_str == "whatsapp":
        msg_type = meta.get("type")
        if msg_type == "reaction":
            return False, "whatsapp_reaction"
        if msg_type == "status":
            return False, "whatsapp_status_receipt"

    return True, None

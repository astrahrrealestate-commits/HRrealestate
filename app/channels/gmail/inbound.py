"""Gmail inbound: normalise a raw-format API message into the `Message` contract."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.channels.gmail.mime import parse_email
from app.channels.gmail.models import GmailMessage
from app.channels.gmail.parsed import ParsedAttachment, ParsedEmail
from app.contracts import Channel, Direction, Message
from app.core.errors import IgnoredMessageError, UnroutableMessageError

# Our own unapproved AI drafts live in this mailbox (Phase 1 output); spam/trash/chat are never conversations.
IGNORED_LABELS = frozenset({"DRAFT", "SPAM", "TRASH", "CHAT"})


def _placeholder(parsed: ParsedEmail) -> str:
    names = [a.filename or a.mime_type for a in parsed.attachments if a.filename or not a.inline]
    if not names:
        return "[no text]"
    noun = "attachment" if len(names) == 1 else "attachments"
    return f"[no text — {len(names)} {noun}: {', '.join(names)}]"


def to_message(
    gm: GmailMessage, *, company_id: UUID, raw_event_id: UUID, mailbox: str
) -> tuple[Message, dict[str, Any], list[ParsedAttachment]]:
    """`Message`, row metadata and attachments (stored by ingestion).

    Raises `UnroutableMessageError` when the message has no usable sender.
    """
    ignored = IGNORED_LABELS.intersection(gm.label_ids)
    if ignored:
        raise IgnoredMessageError(f"gmail message {gm.id} labelled {sorted(ignored)}")
    parsed = parse_email(gm.raw)
    if parsed.from_addr is None:
        raise UnroutableMessageError(f"gmail message {gm.id} has no usable From address")
    mailbox = mailbox.lower()
    # Only Gmail's SENT label proves the owner sent it: a From header equal to the mailbox is trivially forgeable.
    outbound = "SENT" in gm.label_ids
    try:
        message = Message(
            channel=Channel.gmail,
            provider_msg_id=gm.id,
            thread_ref=gm.thread_id,
            sender_identity=mailbox if outbound else parsed.from_addr,
            direction=Direction.outbound if outbound else Direction.inbound,
            sent_at=gm.internal_date,
            text=parsed.text or _placeholder(parsed),
            raw_event_id=raw_event_id,
            company_id=company_id,
        )
    except ValidationError as exc:
        raise UnroutableMessageError(f"gmail message {gm.id}: sender not routable") from exc
    metadata: dict[str, Any] = {
        "type": "email",
        "subject": parsed.subject,
        "message_id": parsed.message_id,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "from": parsed.from_addr,
        "from_name": parsed.from_name,
        "from_self_unsent": (not outbound and parsed.from_addr == mailbox) or None,
        "full_text": parsed.full_text if parsed.quote_stripped else None,
        "skipped_parts": parsed.skipped,
        "parse_error": parsed.parse_error or None,
        "to": parsed.to,
        "cc": parsed.cc,
        "labels": gm.label_ids,
        "quote_stripped": parsed.quote_stripped,
        "history_id": gm.history_id,
    }
    return message, {k: v for k, v in metadata.items() if v not in (None, [], "")}, parsed.attachments

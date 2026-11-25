"""Gmail inbound: normalise a raw-format API message into the `Message` contract."""

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from app.channels.gmail.mime import parse_email
from app.channels.gmail.models import GmailMessage
from app.channels.gmail.parsed import ParsedAttachment, ParsedEmail
from app.contracts import Channel, Direction, Message
from app.contracts.message import normalise_identity
from app.core.errors import IgnoredMessageError, UnroutableMessageError

# Our own unapproved AI drafts live in this mailbox (Phase 1 output); spam/trash/chat are never conversations.
IGNORED_LABELS = frozenset({"DRAFT", "SPAM", "TRASH", "CHAT"})


def _placeholder(parsed: ParsedEmail) -> str:
    names = [a.filename or a.mime_type for a in parsed.attachments if a.filename or not a.inline]
    if not names:
        return "[no text]"
    noun = "attachment" if len(names) == 1 else "attachments"
    return f"[no text — {len(names)} {noun}: {', '.join(names)}]"


def _untagged(address: str) -> str:
    """`name+tag@domain` delivers to `name@domain`."""
    local, _, domain = address.rpartition("@")
    return f"{local.split('+', 1)[0]}@{domain}"


def _is_address(value: str) -> bool:
    if value.startswith("users/"):  # a Google Chat identity, which `normalise_identity` passes unchecked
        return False
    try:
        normalise_identity(value)
    except ValueError:
        return False
    return True


def _real_sender(
    parsed: ParsedEmail, from_addr: str, forwarders: frozenset[str], own: frozenset[str]
) -> tuple[str, str | None, str | None]:
    """(sender address, display name, forwarder) of an inbound mail. In order of preference:

    1. the first usable Reply-To address that is not ours (`own`: team addresses and company mailboxes);
    2. for a mail forwarded by the team (From is one of `forwarders`), the original sender quoted in the forward;
    3. From.
    """
    ours = {_untagged(a) for a in own}
    for address, name in parsed.reply_to:
        if _untagged(address) not in ours and _is_address(address):
            # The From name belongs to another address, so it is only kept when both headers name the same one.
            return address, name or (parsed.from_name if address == from_addr else None), None
    if from_addr in forwarders and parsed.forwarded_from and parsed.forwarded_from not in forwarders:
        return parsed.forwarded_from, parsed.forwarded_from_name, from_addr
    return from_addr, parsed.from_name, None


def to_message(
    gm: GmailMessage,
    *,
    company_id: UUID,
    raw_event_id: UUID,
    mailbox: str,
    forwarders: frozenset[str] = frozenset(),
    own_addresses: frozenset[str] = frozenset(),
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
    sender, sender_name, forwarded_by = (
        (parsed.from_addr, parsed.from_name, None)
        if outbound
        else _real_sender(parsed, parsed.from_addr, forwarders, forwarders | own_addresses | {mailbox})
    )
    try:
        message = Message(
            channel=Channel.gmail,
            provider_msg_id=gm.id,
            thread_ref=gm.thread_id,
            sender_identity=mailbox if outbound else sender,
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
        "mailbox": mailbox,  # the company mailbox it arrived in: replies are drafted in this same mailbox
        "subject": parsed.subject,
        "message_id": parsed.message_id,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "from": sender,
        "from_name": sender_name,
        "forwarded_by": forwarded_by,
        # The From header whenever someone else was taken as the sender: Reply-To is not authenticated.
        "header_from": parsed.from_addr if sender != parsed.from_addr and not forwarded_by else None,
        "from_self_unsent": (not outbound and parsed.from_addr == mailbox) or None,
        "full_text": parsed.full_text if parsed.quote_stripped else None,
        "body_html": parsed.html,
        "skipped_parts": parsed.skipped,
        "parse_error": parsed.parse_error or None,
        "to": parsed.to,
        "cc": parsed.cc,
        "labels": gm.label_ids,
        "quote_stripped": parsed.quote_stripped,
        "history_id": gm.history_id,
    }
    return message, {k: v for k, v in metadata.items() if v not in (None, [], "")}, parsed.attachments

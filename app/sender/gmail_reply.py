"""A reply in the tenant's Gmail thread: the thread's own mailbox, reply headers from the stored message."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, DraftRequest
from app.db.models import ActionRow, ChannelAccount, MessageRow, RawEvent
from app.sender.errors import SendBlockedError
from app.sender.plan import Plan
from app.sender.recipient import latest_inbound


def thread_mailbox(session: Session, msg: MessageRow) -> str | None:
    """The company mailbox the thread lives in: recorded at ingest, else from the raw event (rows before that).

    Only one of the company's own Gmail accounts qualifies: a thread id is only valid in its own mailbox.
    """
    address = msg.meta.get("mailbox") or session.scalar(
        select(RawEvent.payload["mailbox"].astext).where(
            RawEvent.id == msg.raw_event_id, RawEvent.company_id == msg.company_id
        )
    )
    if not address:
        return session.scalar(
            select(ChannelAccount.address).where(
                ChannelAccount.company_id == msg.company_id,
                ChannelAccount.channel == Channel.gmail,
            )
        )
    return session.scalar(
        select(ChannelAccount.address).where(
            ChannelAccount.company_id == msg.company_id,
            ChannelAccount.channel == Channel.gmail,
            ChannelAccount.address == str(address).lower(),
        )
    )


_RE_PREFIX = re.compile(r"^\s*(re\s*:\s*)+", re.IGNORECASE)


def thread_subject(stored: str | None) -> str:
    """`Re: <thread subject>` from the stored inbound subject only (repeated `Re:` collapsed); `Re:` when none."""
    rest = _RE_PREFIX.sub("", stored or "").strip()
    return f"Re: {rest}" if rest else "Re:"


def _draft_subject(action: ActionRow, msg: MessageRow) -> str:
    """Draft mode (unchanged): the proposal's subject or the thread's; Harjot sees and edits it in Gmail."""
    subject = action.payload.get("subject") or msg.meta.get("subject") or ""
    return subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()


def reply_plan(session: Session, msg: MessageRow, to: str, subject: str, body: str, key: str) -> Plan:
    """A reply to `msg` in its thread, addressed to `to` (the caller decides who that may be, and the subject)."""
    if not msg.thread_ref:
        raise SendBlockedError("no Gmail thread on this case to draft a reply in")
    mailbox = thread_mailbox(session, msg)
    if mailbox is None:
        raise SendBlockedError("the mailbox this Gmail thread arrived in is not one of the company's accounts")
    rfc_id = msg.meta.get("message_id")
    refs = " ".join(r for r in (msg.meta.get("references"), rfc_id) if r) or None
    draft = DraftRequest(key, msg.thread_ref, to, subject, body, in_reply_to=rfc_id, references=refs)
    return Plan(Channel.gmail, to, draft=draft, mailbox=mailbox)


def gmail_draft(session: Session, action: ActionRow, body: str, key: str) -> Plan:
    """Draft mode: a draft in the thread of the case's latest Gmail inbound. Harjot reviews and sends it himself."""
    msg = latest_inbound(session, action.company_id, action.case_id, Channel.gmail)
    if msg is None or not msg.thread_ref:
        raise SendBlockedError("no Gmail thread on this case to draft a reply in")
    return reply_plan(session, msg, msg.sender_identity, _draft_subject(action, msg), body, key)

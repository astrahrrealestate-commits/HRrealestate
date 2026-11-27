"""A reply in the tenant's Gmail thread: the thread's own mailbox, reply headers from the stored message."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction, DraftRequest
from app.db.models import ActionRow, CaseLink, ChannelAccount, MessageRow, RawEvent
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


def assert_addressee(session: Session, action: ActionRow, latest: MessageRow) -> None:
    """A case holding repaired forwards (ADR 0016) can be shared by several people. There, a draft goes to the latest
    sender only when the reply answers that person's mail; a reply that answers none (a chaser) needs one sender."""
    linked = (
        select(MessageRow.id, MessageRow.thread_ref)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == action.company_id,
            CaseLink.case_id == action.case_id,
            MessageRow.company_id == action.company_id,
        )
        .subquery()
    )
    incoming = session.execute(
        select(MessageRow.id, MessageRow.sender_identity, MessageRow.meta.has_key("reattributed_from")).where(
            MessageRow.company_id == action.company_id,
            # The inbox shows a thread's other messages on the case too, so they count as sharing it.
            MessageRow.id.in_(select(linked.c.id)) | MessageRow.thread_ref.in_(select(linked.c.thread_ref)),
            MessageRow.channel == Channel.gmail,
            MessageRow.direction == Direction.inbound,
        )
    ).all()
    if not any(repaired for _, _, repaired in incoming):
        return
    senders = {message_id: sender.lower() for message_id, sender, _ in incoming}
    answered = {senders[ref] for ref in action.context_ref or () if ref in senders} or set(senders.values())
    if answered != {latest.sender_identity.lower()}:
        raise SendBlockedError("this case holds mail from several senders: sort it before drafting this reply")


def gmail_draft(session: Session, action: ActionRow, body: str, key: str) -> Plan:
    """Draft mode: a draft in the thread of the case's latest Gmail inbound. Harjot reviews and sends it himself."""
    from dataclasses import replace
    from uuid import UUID

    msg = latest_inbound(session, action.company_id, action.case_id, Channel.gmail)
    if msg is None or not msg.thread_ref:
        raise SendBlockedError("no Gmail thread on this case to draft a reply in")
    assert_addressee(session, action, msg)
    plan = reply_plan(session, msg, msg.sender_identity, _draft_subject(action, msg), body, key)
    raw_ids = (action.payload or {}).get("attachment_ids") or ()
    att_ids = tuple(UUID(str(x)) for x in raw_ids if str(x))
    return replace(plan, company_id=action.company_id, attachment_ids=att_ids) if att_ids else plan

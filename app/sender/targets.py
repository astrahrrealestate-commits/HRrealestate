"""Where an approved action goes. Recipients come from the DB only (invariant 6), never from model output.

Phase 1 allowlist: a Gmail *draft* in the tenant's thread, or a WhatsApp message to one of the company's owner
numbers. A tenant-facing WhatsApp reply is delivered to the owner as copy-ready text.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import DraftRequest
from app.channels.whatsapp import payloads
from app.contracts import ActionType, Channel, Direction
from app.core.errors import EstateOSError
from app.db.models import ActionRow, CaseLink, ChannelAccount, ChannelIdentity, MessageRow, OwnerAccount, Person


class SendBlockedError(EstateOSError):
    """The action cannot be delivered within the Phase 1 rules (no thread, no owner number, not allowed)."""


@dataclass(frozen=True)
class Plan:
    channel: Channel
    target: str  # owner E.164 for WhatsApp, tenant address for a Gmail draft (audit only; Gmail drafts are not sent)
    whatsapp: dict[str, Any] | None = None
    draft: DraftRequest | None = None
    mailbox: str | None = None


def owner_number(session: Session, company_id: UUID) -> str:
    number = session.scalar(
        select(OwnerAccount.whatsapp_e164)
        .where(OwnerAccount.company_id == company_id)
        .order_by(OwnerAccount.created_at)
    )
    if number is None:
        raise SendBlockedError("company has no owner WhatsApp number")
    return number


def _owner_text(session: Session, company_id: UUID, body: str) -> Plan:
    to = owner_number(session, company_id)
    return Plan(Channel.whatsapp, to, whatsapp=payloads.text(to, body[: payloads.TEXT_BODY_MAX]))


def _latest_inbound(session: Session, company_id: UUID, case_id: UUID, channel: Channel) -> MessageRow | None:
    return session.scalar(
        select(MessageRow)
        .join(CaseLink, CaseLink.message_id == MessageRow.id)
        .where(
            CaseLink.company_id == company_id,
            CaseLink.case_id == case_id,
            MessageRow.channel == channel,
            MessageRow.direction == Direction.inbound,
        )
        .order_by(MessageRow.sent_at.desc())
        .limit(1)
    )


def _gmail_draft(session: Session, action: ActionRow, body: str, key: str) -> Plan:
    msg = _latest_inbound(session, action.company_id, action.case_id, Channel.gmail)
    mailbox = session.scalar(
        select(ChannelAccount.address).where(
            ChannelAccount.company_id == action.company_id, ChannelAccount.channel == Channel.gmail
        )
    )
    if msg is None or not msg.thread_ref or mailbox is None:
        raise SendBlockedError("no Gmail thread on this case to draft a reply in")
    subject = action.payload.get("subject") or msg.meta.get("subject") or ""
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()
    rfc_id = msg.meta.get("message_id")
    refs = " ".join(r for r in (msg.meta.get("references"), rfc_id) if r) or None
    draft = DraftRequest(key, msg.thread_ref, msg.sender_identity, subject, body, in_reply_to=rfc_id, references=refs)
    return Plan(Channel.gmail, msg.sender_identity, draft=draft, mailbox=mailbox)


def _contact(session: Session, company_id: UUID, person_id: UUID) -> str:
    name = session.scalar(select(Person.display_name).where(Person.id == person_id, Person.company_id == company_id))
    idents = session.scalars(
        select(ChannelIdentity.identity).where(
            ChannelIdentity.company_id == company_id,
            ChannelIdentity.person_id == person_id,
            ChannelIdentity.valid_to.is_(None),
        )
    ).all()
    if name is None:
        raise SendBlockedError("contractor is not a person of this company")
    return f"{name} ({', '.join(idents) or 'no contact on file'})"


def _counterpart(session: Session, action: ActionRow) -> str:
    msg = _latest_inbound(session, action.company_id, action.case_id, Channel.whatsapp)
    return msg.sender_identity if msg else "the tenant"


def plan_for(session: Session, action: ActionRow, variant: int, key: str) -> Plan:
    payload = action.payload
    variants: list[str] = payload.get("body_variants") or []
    body = variants[min(variant, len(variants) - 1)] if variants else ""
    if action.type is ActionType.reply_draft and payload.get("channel") == Channel.gmail.value:
        return _gmail_draft(session, action, body, key)
    if action.type is ActionType.reply_draft:
        who = _counterpart(session, action)
        return _owner_text(session, action.company_id, f"Approved reply for {who}. Copy and send:\n\n{body}")
    if action.type is ActionType.request_contractor:
        who = _contact(session, action.company_id, UUID(payload["contractor_person_id"]))
        return _owner_text(session, action.company_id, f"Approved request for {who}. Copy and send:\n\n{body}")
    if action.type is ActionType.notify_owner:
        return _owner_text(session, action.company_id, str(payload["text"]))
    if action.type is ActionType.escalate:
        return _owner_text(session, action.company_id, f"Escalation: {payload['reason']}")
    raise SendBlockedError(f"{action.type.value} actions are not delivered by the sender")


def assert_allowed(session: Session, company_id: UUID, plan: Plan) -> None:
    """Phase 1: nothing reaches a tenant. Re-checked right before every provider call."""
    if plan.channel is Channel.gmail and plan.draft is not None and plan.whatsapp is None:
        return
    owners = set(session.scalars(select(OwnerAccount.whatsapp_e164).where(OwnerAccount.company_id == company_id)))
    payload_to = "+" + str((plan.whatsapp or {}).get("to", "")).removeprefix("+")
    if plan.channel is Channel.whatsapp and plan.target in owners and payload_to == plan.target and plan.draft is None:
        return  # the recipient actually in the payload is checked too, not only the planned target
    raise SendBlockedError("Phase 1 allowlist: only Gmail drafts and messages to the owner")

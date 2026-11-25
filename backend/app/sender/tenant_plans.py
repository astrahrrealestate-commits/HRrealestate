"""Send mode (spec §5): approved replies that reach the tenant. Only built when `companies.outbound_mode` is `send`.

The recipient is always `recipient.tenant_recipient`'s canonical identity, never a payload, model or raw sender
value. `assert_tenant` re-reads the mode and re-derives the recipient right before the claim; the plan is not trusted.
"""

from dataclasses import replace
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import Channel, OutboundMode
from app.db.models import ActionRow, Company
from app.sender.errors import SendBlockedError
from app.sender.gmail_reply import assert_addressee, reply_plan, thread_subject
from app.sender.plan import Plan
from app.sender.recipient import tenant_recipient, whatsapp_window_open

WINDOW_CLOSED = "WhatsApp window closed: the tenant wrote more than 23 h ago; reply by email or wait"
UNSUPPORTED_CHANNEL = "unsupported reply channel"
EMPTY_BODY = "the approved reply is empty"
TOO_LONG = f"the approved reply is longer than WhatsApp's {payloads.TEXT_BODY_MAX} characters; shorten it or use email"


def body_refusal(body: str, channel: Channel) -> str | None:
    """The approved text is sent exactly as approved, or not at all: never trimmed."""
    if not body.strip():
        return EMPTY_BODY
    if channel is Channel.whatsapp and len(body) > payloads.TEXT_BODY_MAX:
        return TOO_LONG
    return None


def reply_channel(payload_channel: object) -> Channel:
    """Send mode answers only on the channel the proposal names: "gmail" or "whatsapp", nothing else."""
    if payload_channel == Channel.gmail.value:
        return Channel.gmail
    if payload_channel == Channel.whatsapp.value:
        return Channel.whatsapp
    raise SendBlockedError(UNSUPPORTED_CHANNEL)


def _checked_body(body: str, channel: Channel) -> str:
    reason = body_refusal(body, channel)
    if reason is not None:
        raise SendBlockedError(reason)
    return body


def tenant_gmail(session: Session, action: ActionRow, body: str, key: str) -> Plan:
    """A reply in the thread of the contact's own latest message, to the contact's identity. The subject comes from
    the stored thread only, never from the proposal (model text Harjot did not see as the subject)."""
    msg, to = tenant_recipient(session, action.company_id, action.case_id, Channel.gmail)
    assert_addressee(session, action, msg)
    subject = thread_subject(msg.meta.get("subject"))
    plan = reply_plan(session, msg, to, subject, _checked_body(body, Channel.gmail), key)
    return replace(plan, tenant_send=True, case_id=action.case_id)


def tenant_whatsapp(session: Session, action: ActionRow, body: str, now: datetime) -> Plan:
    """Free-form text to the contact's number, only inside the 23 h window of the contact's own last message."""
    msg, to = tenant_recipient(session, action.company_id, action.case_id, Channel.whatsapp)
    if not whatsapp_window_open(msg, now):
        raise SendBlockedError(WINDOW_CLOSED)
    payload = payloads.text(to, _checked_body(body, Channel.whatsapp))
    return Plan(Channel.whatsapp, to, whatsapp=payload, tenant_send=True, case_id=action.case_id)


def tenant_plan(session: Session, action: ActionRow, body: str, key: str, now: datetime) -> Plan:
    if reply_channel(action.payload.get("channel")) is Channel.gmail:
        return tenant_gmail(session, action, body, key)
    return tenant_whatsapp(session, action, body, now)


def _shape_refusal(plan: Plan) -> str | None:
    """The address actually handed to the provider must be the planned target, and only one kind of payload."""
    if plan.channel is Channel.gmail:
        ok = plan.draft is not None and plan.mailbox is not None and plan.draft.to == plan.target
        return None if ok and plan.whatsapp is None and plan.email is None else "tenant email plan is malformed"
    if plan.channel is Channel.whatsapp:
        to = "+" + str((plan.whatsapp or {}).get("to", "")).removeprefix("+")
        ok = plan.whatsapp is not None and to == plan.target
        return None if ok and plan.draft is None and plan.email is None else "tenant WhatsApp plan is malformed"
    return f"{plan.channel.value} is not a tenant reply channel"


def tenant_refusal(plan: Plan, mode: OutboundMode | None, expected: str | None) -> str | None:
    """Pure allowlist decision for a tenant plan: the mode re-read now and the recipient re-derived now."""
    if not plan.tenant_send:
        return "not a tenant send"
    if mode is not OutboundMode.send:
        return "outbound mode is not send: tenant replies are drafts only"
    if expected is None or plan.target != expected:
        return "recipient is not the case contact"
    return _shape_refusal(plan)


def assert_tenant(session: Session, company_id: UUID, plan: Plan) -> None:
    """Raise unless the company is in send mode *now* and the target is the contact re-derived from the DB *now*."""
    mode = session.scalar(select(Company.outbound_mode).where(Company.id == company_id))
    expected: str | None = None
    if plan.tenant_send and mode is OutboundMode.send and plan.case_id is not None:
        _, expected = tenant_recipient(session, company_id, plan.case_id, plan.channel)
    reason = tenant_refusal(plan, mode, expected)
    if reason is not None:
        raise SendBlockedError(reason)

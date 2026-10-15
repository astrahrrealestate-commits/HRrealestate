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
from app.sender.gmail_reply import reply_plan
from app.sender.plan import Plan
from app.sender.recipient import tenant_recipient, whatsapp_window_open

WINDOW_CLOSED = "WhatsApp window closed: the tenant wrote more than 23 h ago; reply by email or wait"


def tenant_gmail(session: Session, action: ActionRow, body: str, key: str) -> Plan:
    """A reply sent in the thread of the contact's own latest message, addressed to the contact's identity."""
    msg, to = tenant_recipient(session, action.company_id, action.case_id, Channel.gmail)
    return replace(reply_plan(session, action, msg, to, body, key), tenant_send=True, case_id=action.case_id)


def tenant_whatsapp(session: Session, action: ActionRow, body: str, now: datetime) -> Plan:
    """Free-form text to the contact's number, only inside the 23 h window of the contact's own last message."""
    msg, to = tenant_recipient(session, action.company_id, action.case_id, Channel.whatsapp)
    if not whatsapp_window_open(msg, now):
        raise SendBlockedError(WINDOW_CLOSED)
    payload = payloads.text(to, body[: payloads.TEXT_BODY_MAX])
    return Plan(Channel.whatsapp, to, whatsapp=payload, tenant_send=True, case_id=action.case_id)


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

"""Extra send-mode guards checked in the claim transaction (spec §5), and telling Harjot when a tenant send failed.

Credential separation note: Gmail's `gmail.compose` scope (the drafts/digest token) can technically call
`messages.send` too. Separation is therefore enforced in code, not by OAuth scope alone: `assert_allowed` lets
`send_message` reach only the owner's own email addresses, tenant replies only go through `send_reply` on the
adapter built from the separate GMAIL_REPLY_SEND_CREDENTIALS_FILE (`SenderDeps.gmail_sender`), and only for plans
`assert_tenant` accepted.
"""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.contracts import Channel, OwnerMessage
from app.core.logging import get_logger
from app.db.enums import FeedKind, SendStatus
from app.db.models import OwnerAccount, Send
from app.sender.plan import Plan

log = get_logger(__name__)
CAP_REACHED = "hourly tenant send cap reached"
GMAIL_SEND_MISSING = "Gmail sending is not configured: GMAIL_REPLY_SEND_CREDENTIALS_FILE (gmail.send) is missing"
CAP_WINDOW = timedelta(hours=1)
_COUNTED = (SendStatus.pending, SendStatus.sending, SendStatus.sent)


def cap_reached(recent: int, cap: int) -> bool:
    """At or over the cap refuses; a cap of 0 or less refuses every tenant send."""
    return recent >= cap


def tenant_sends_last_hour(session: Session, company_id: UUID, key: str, now: datetime) -> int:
    """Gmail/WhatsApp `sends` of the company in the last hour that did not go to an owner (this key excluded)."""
    owner_rows = session.execute(
        select(OwnerAccount.whatsapp_e164, OwnerAccount.email).where(OwnerAccount.company_id == company_id)
    ).all()
    owners = {value for row in owner_rows for value in row if value}
    owners |= {value.lower() for value in owners}
    count = session.scalar(
        select(func.count())
        .select_from(Send)
        .where(
            Send.company_id == company_id,
            Send.created_at > now - CAP_WINDOW,
            Send.channel.in_((Channel.gmail, Channel.whatsapp)),
            Send.status.in_(_COUNTED),
            Send.target.not_in(owners),
            Send.idempotency_key != key,
        )
    )
    return int(count or 0)


def tenant_gate(
    session: Session, company_id: UUID, key: str, plan: Plan, now: datetime, *, cap: int, gmail_send_ready: bool
) -> str | None:
    """Why a tenant plan may not be claimed, or None. Owner-directed and draft plans pass untouched.

    The caller (`execute._prepare`) holds the company row FOR NO KEY UPDATE, so concurrent tenant sends of one
    company count each other against the cap.
    """
    if not plan.tenant_send:
        return None
    if plan.channel is Channel.gmail and not gmail_send_ready:
        return GMAIL_SEND_MISSING
    if cap_reached(tenant_sends_last_hour(session, company_id, key, now), cap):
        return CAP_REACHED
    return None


def blocked_key(action_id: UUID, draft_version: int) -> str:
    """`blocked:{exec_key}`: the key `actions.tell_blocked_step` uses too, so the dashboard shows one row."""
    return f"blocked:exec:{action_id}:{draft_version}"


_MAYBE_SENT = ("delivery status unknown", "may have been delivered")


def alert_text(reason: str | None) -> str:
    """The alert line; an attempt that may have reached the tenant never claims "not sent"."""
    maybe = (reason or "").startswith(_MAYBE_SENT)
    lead = "Reply may not have reached the tenant" if maybe else "Reply not sent to the tenant"
    return f"{lead}: {reason or 'unknown reason'}."


def tell_owner(engine: Engine, company_id: UUID, action_id: UUID, draft_version: int, reason: str | None) -> None:
    """One dashboard alert per action version saying why the reply did not reach the tenant (no message body)."""
    text = alert_text(reason)
    try:
        with Session(engine) as session, session.begin():
            key = blocked_key(action_id, draft_version)
            feed.deliver(session, company_id, key, FeedKind.alert, None, OwnerMessage(text=text))
    except Exception as exc:  # telling must never turn a recorded outcome into an error
        log.error("sender.tell_owner_failed", action_id=str(action_id), error=type(exc).__name__)

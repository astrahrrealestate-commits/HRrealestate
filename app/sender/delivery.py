"""Delivery core shared by actions and owner messages: claim a `sends` row, one provider attempt, record it.

`send_claimed` lets exactly one attempt call the provider (`pending → sending`). A definitely-not-sent transient error
returns the row to pending and re-raises for the step retry; anything else is recorded as failed, never re-sent.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import GmailDrafts
from app.channels.google_chat.outbound import GoogleChatOutbound
from app.channels.whatsapp.outbound import WhatsAppOutbound
from app.contracts import Channel
from app.core.errors import EstateOSError
from app.db.enums import ActionStatus, SendStatus
from app.db.models import ActionRow, Send
from app.sender.errors import SendBlockedError
from app.sender.plan import Plan
from app.sender.tenant_gate import GMAIL_SEND_MISSING


@dataclass(frozen=True)
class SenderDeps:
    engine: Engine
    whatsapp: WhatsAppOutbound
    gmail_drafts: Callable[[str], GmailDrafts]  # mailbox address → drafts adapter
    google_chat: GoogleChatOutbound | None = None
    template_name: str = "estateos_pending"
    template_language: str = "en"
    # Send mode: mailbox → adapter built with the separate `gmail.send` token; None = tenant Gmail sends blocked.
    gmail_sender: Callable[[str], GmailDrafts] | None = None
    tenant_sends_per_hour: int = 30


@dataclass(frozen=True)
class ExecOutcome:
    status: Literal["sent", "already", "blocked", "failed"]
    reason: str | None = None
    provider_ref: str | None = None


def exec_key(action_id: UUID, draft_version: int) -> str:
    return f"exec:{action_id}:{draft_version}"


REUSED_KEY = "an earlier send under this key went to a different recipient or channel"
STATUS_UNKNOWN = "delivery status unknown: a previous attempt did not finish; check the thread before resending"


def reuse_refusal(send: Send, company_id: UUID, plan: Plan) -> str | None:
    """A `sends` row is only ever reused for the same company, channel and recipient (never owner ↔ tenant)."""
    same = send.company_id == company_id and send.channel is plan.channel and send.target == plan.target
    return None if same else REUSED_KEY


def claim(session: Session, company_id: UUID, key: str, action_id: UUID | None, plan: Plan) -> Send:
    """Insert-or-lock the `sends` row for `key`. Raises SendBlockedError when the existing row is for another
    recipient or channel."""
    session.execute(
        insert(Send)
        .values(
            company_id=company_id, action_id=action_id, idempotency_key=key, channel=plan.channel, target=plan.target
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    send = session.execute(select(Send).where(Send.idempotency_key == key).with_for_update()).scalar_one()
    reason = reuse_refusal(send, company_id, plan)
    if reason is not None:
        raise SendBlockedError(reason)
    return send


def deliver(deps: SenderDeps, plan: Plan) -> str:
    if plan.tenant_send and plan.channel is Channel.gmail:
        if deps.gmail_sender is None or plan.draft is None or plan.mailbox is None:
            raise SendBlockedError(GMAIL_SEND_MISSING)
        return deps.gmail_sender(plan.mailbox).send_reply(plan.draft)
    if plan.tenant_send and plan.channel is not Channel.whatsapp:
        raise SendBlockedError(f"{plan.channel.value} is not a tenant reply channel")
    if plan.channel is Channel.gmail and plan.draft is not None and plan.mailbox is not None:
        return deps.gmail_drafts(plan.mailbox).create_draft(plan.draft)
    if plan.channel is Channel.gmail and plan.email is not None and plan.mailbox is not None:
        return deps.gmail_drafts(plan.mailbox).send_message(plan.email)
    if plan.channel is Channel.google_chat and plan.google_chat is not None:
        if deps.google_chat is None:
            raise SendBlockedError("Google Chat outbound not configured")
        return deps.google_chat.send(plan.target, plan.google_chat)
    if plan.whatsapp is not None:
        return deps.whatsapp.send(plan.whatsapp)
    raise SendBlockedError("nothing to deliver")


def mark(engine: Engine, key: str, status: SendStatus, ref: str | None, error: str | None) -> None:
    with Session(engine) as session, session.begin():
        send = session.execute(select(Send).where(Send.idempotency_key == key)).scalar_one()
        send.status, send.provider_ref, send.error = status, ref, error
        send.attempted_at = datetime.now(UTC)
        if send.action_id is not None and status is not SendStatus.pending:
            action = session.get(ActionRow, send.action_id)
            if action is not None:
                action.status = ActionStatus.executed if status is SendStatus.sent else ActionStatus.failed


class SendFailedError(EstateOSError):
    """An owner message the provider rejected for good (never retried automatically)."""


def begin_attempt(engine: Engine, key: str) -> bool:
    """Atomic `pending → sending`: exactly one attempt may call the provider for a send."""
    with Session(engine) as session, session.begin():
        won = session.execute(
            update(Send)
            .where(Send.idempotency_key == key, Send.status == SendStatus.pending)
            .values(status=SendStatus.sending, attempted_at=datetime.now(UTC))
            .returning(Send.id)
        ).first()
    return won is not None


def lost_attempt(tenant_send: bool, status: SendStatus | None, ref: str | None) -> ExecOutcome:
    """Another attempt holds or finished the send. Sent → already. For a tenant message a `sending`/`failed` row
    is not "done": nobody knows whether the tenant got it, so it is reported as failed (Harjot checks the thread).
    Owner-directed messages keep "already" (the holder reports its own outcome)."""
    if status is SendStatus.sent:
        return ExecOutcome("already", provider_ref=ref)
    if tenant_send:
        return ExecOutcome("failed", reason=STATUS_UNKNOWN)
    return ExecOutcome("already", reason="another attempt holds this send")


def _current(engine: Engine, key: str) -> tuple[SendStatus | None, str | None]:
    with Session(engine) as session:
        row = session.execute(select(Send.status, Send.provider_ref).where(Send.idempotency_key == key)).first()
    return (row[0], row[1]) if row is not None else (None, None)


def send_claimed(deps: SenderDeps, key: str, plan: Plan) -> ExecOutcome:
    if not begin_attempt(deps.engine, key):  # another attempt holds it, or it already finished
        return lost_attempt(plan.tenant_send, *_current(deps.engine, key))
    try:
        ref = deliver(deps, plan)
    except Exception as exc:
        if getattr(exc, "retryable", False):  # definitely not delivered: free it for the step retry
            mark(deps.engine, key, SendStatus.pending, None, f"{type(exc).__name__}: {str(exc)[:300]}")
            raise
        prefix = "may have been delivered: " if getattr(exc, "maybe_sent", False) else ""
        reason = f"{prefix}{type(exc).__name__}: {str(exc)[:200]}"
        mark(deps.engine, key, SendStatus.failed, None, reason)
        return ExecOutcome("failed", reason=reason)
    mark(deps.engine, key, SendStatus.sent, ref, None)
    return ExecOutcome("sent", provider_ref=ref)

"""Delivery core shared by actions and owner messages: claim a `sends` row, one provider attempt, record it.

`send_claimed` lets exactly one attempt call the provider (`pending → sending`). A definitely-not-sent transient error
returns the row to pending and re-raises for the step retry; anything else is recorded as failed, never re-sent.
A dashboard plan has no provider: its `owner_feed` row (same key) and the `sent` mark commit in one transaction, so
a database error leaves nothing half-done and the step retry simply runs it again.

An attempt that loses the claim to a send still `sending` reports `in_progress` (no failure, no alert, no follow-up
wait; "already" only ever means sent). For a tenant send that row is left to its holder while younger than
`STUCK_AFTER`; an older one never reported back (the worker died mid-call), so the row and the action are marked failed
once (`STUCK`, one alert) and Harjot checks the thread before resending by hand. The 5-minute sweep
(`app.sender.stuck`) does the same for rows nobody re-attempts. A failed action is never re-run by `resume`.

Lock order: `feed_claimed` and `give_up_stuck` lock the action row before the `sends` row (Company -> Action -> Send,
as `execute._prepare`). `mark` writes the send first; only the attempt holding the claim calls it, and a rare
deadlock with a give-up is aborted by Postgres and retried by the step.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.dashboard import feed
from app.channels.gmail.drafts import GmailDrafts
from app.channels.google_chat.outbound import GoogleChatOutbound
from app.channels.whatsapp.outbound import WhatsAppOutbound
from app.contracts import Channel
from app.core.errors import EstateOSError
from app.db.enums import ActionStatus, SendStatus
from app.db.models import ActionRow, Send
from app.sender.errors import SendBlockedError
from app.sender.plan import Plan
from app.sender.tenant_gate import GMAIL_SEND_MISSING, write_alert


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
    owner_chat_sends_per_hour: int = 200
    owner_chat_sends_per_number_per_hour: int = 20


@dataclass(frozen=True)
class ExecOutcome:
    status: Literal["sent", "already", "in_progress", "blocked", "failed"]
    reason: str | None = None
    provider_ref: str | None = None


def exec_key(action_id: UUID, draft_version: int) -> str:
    return f"exec:{action_id}:{draft_version}"


REUSED_KEY = "an earlier send under this key went to a different recipient or channel"
STATUS_UNKNOWN = "delivery status unknown: a previous attempt did not finish; check the thread before resending"
STUCK = "delivery status unknown: previous attempt never reported; check the thread before resending it yourself"
IN_PROGRESS = "in progress: another attempt is sending this message"
STUCK_AFTER = timedelta(minutes=30)  # a provider call never takes this long: the attempt died without reporting


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


def stuck(attempted_at: datetime | None, now: datetime) -> bool:
    """A `sending` row whose attempt started `STUCK_AFTER` ago (or never recorded a start) will not report back."""
    return attempted_at is None or now - attempted_at >= STUCK_AFTER


def lost_attempt(
    tenant_send: bool,
    status: SendStatus | None,
    ref: str | None,
    attempted_at: datetime | None = None,
    now: datetime | None = None,
) -> ExecOutcome:
    """Another attempt holds or finished the send. Sent → already (the only "done"). For a tenant message a recent
    `sending` row is `in_progress` (no alert); a stuck one is `STUCK` (the caller marks it failed once); a `failed`
    row is not "done": nobody knows whether the tenant got it, so it is reported as failed (Harjot checks the thread).
    Owner-directed messages are `in_progress` (the holder reports its own outcome)."""
    if status is SendStatus.sent:
        return ExecOutcome("already", provider_ref=ref)
    if not tenant_send:
        return ExecOutcome("in_progress", reason="another attempt holds this send")
    if status is SendStatus.sending:
        if stuck(attempted_at, now or datetime.now(UTC)):
            return ExecOutcome("failed", reason=STUCK)
        return ExecOutcome("in_progress", reason=IN_PROGRESS)
    return ExecOutcome("failed", reason=STATUS_UNKNOWN)


def _lock_action(session: Session, key: str, company_id: UUID | None) -> None:
    """Lock the send's action row first (Company -> Action -> Send, as `execute._prepare`)."""
    scope = [Send.company_id == company_id] if company_id is not None else []
    action_id = session.scalar(select(Send.action_id).where(Send.idempotency_key == key, *scope))
    if action_id is not None:
        action_scope = [ActionRow.company_id == company_id] if company_id is not None else []
        session.execute(select(ActionRow.id).where(ActionRow.id == action_id, *action_scope).with_for_update())


def give_up_stuck(engine: Engine, key: str, now: datetime, *, company_id: UUID | None = None) -> bool:
    """Mark a stuck `sending` row and its action failed and write the one alert (`blocked:{key}`), in one
    transaction. The conditional UPDATE has one winner: True only for that caller, so nobody alerts twice."""
    scope = [Send.company_id == company_id] if company_id is not None else []
    with Session(engine) as session, session.begin():
        _lock_action(session, key, company_id)
        row = session.execute(
            update(Send)
            .where(
                Send.idempotency_key == key,
                *scope,
                Send.status == SendStatus.sending,
                (Send.attempted_at.is_(None)) | (Send.attempted_at <= now - STUCK_AFTER),
            )
            .values(status=SendStatus.failed, error=STUCK)
            .returning(Send.action_id, Send.company_id)
        ).first()
        if row is not None and row[0] is not None:
            action = ActionRow.id == row[0], ActionRow.company_id == row[1]
            session.execute(update(ActionRow).where(*action).values(status=ActionStatus.failed))
            write_alert(session, row[1], f"blocked:{key}", STUCK)
    return row is not None


def _current(engine: Engine, key: str) -> tuple[SendStatus | None, str | None, datetime | None]:
    with Session(engine) as session:
        row = session.execute(
            select(Send.status, Send.provider_ref, Send.attempted_at).where(Send.idempotency_key == key)
        ).first()
    return (row[0], row[1], row[2]) if row is not None else (None, None, None)


def _lost(engine: Engine, key: str, plan: Plan) -> ExecOutcome:
    now = datetime.now(UTC)
    outcome = lost_attempt(plan.tenant_send, *_current(engine, key), now)
    if outcome.reason == STUCK and not give_up_stuck(engine, key, now):
        return lost_attempt(plan.tenant_send, *_current(engine, key), now)  # another caller marked it first
    return outcome


def feed_claimed(engine: Engine, key: str, plan: Plan) -> ExecOutcome:
    """Deliver a claimed dashboard plan: the feed row, the `sends` row marked sent and the action executed, at once."""
    if plan.company_id is None or plan.owner_message is None:
        raise SendBlockedError("nothing to deliver")
    with Session(engine) as session, session.begin():
        _lock_action(session, key, plan.company_id)  # Action before Send, like every other claim path
        send = session.execute(select(Send).where(Send.idempotency_key == key).with_for_update()).scalar_one()
        if send.status is SendStatus.sent:
            return ExecOutcome("already", provider_ref=send.provider_ref)
        kind = feed.kind_for_key(key)
        row_id = feed.deliver(session, plan.company_id, key, kind, None, plan.owner_message)
        send.status, send.provider_ref, send.error, send.attempted_at = SendStatus.sent, str(row_id), None, _now()
        if send.action_id is not None:
            session.execute(
                update(ActionRow).where(ActionRow.id == send.action_id).values(status=ActionStatus.executed)
            )
    return ExecOutcome("sent", provider_ref=str(row_id))


def _now() -> datetime:
    return datetime.now(UTC)


def send_claimed(deps: SenderDeps, key: str, plan: Plan) -> ExecOutcome:
    if plan.channel is Channel.dashboard:  # no provider call: nothing can be half-sent
        return feed_claimed(deps.engine, key, plan)
    if not begin_attempt(deps.engine, key):  # another attempt holds it, or it already finished
        return _lost(deps.engine, key, plan)
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

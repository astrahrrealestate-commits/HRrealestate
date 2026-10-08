"""The only code path that delivers anything (invariant 5).

`execute_action` re-checks, in one locked transaction: approval approved for this draft version, the action still on
that version, the company not paused, the Phase 1 allowlist and `sends.idempotency_key`. The provider call happens
after that commit; a retry finds the `sends` row and never delivers twice once it is marked sent.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.channels.gmail.drafts import GmailDrafts
from app.channels.whatsapp import payloads
from app.channels.whatsapp.outbound import WhatsAppOutbound
from app.contracts import ButtonChoice, Channel
from app.core.errors import EstateOSError
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus, OutboxStatus, SendStatus
from app.db.models import ActionRow, Approval, Company, OwnerOutbox, Send
from app.sender import owner_window
from app.sender.targets import Plan, SendBlockedError, assert_allowed, owner_number, plan_for

log = get_logger(__name__)
_VARIANT = {ButtonChoice.d2: 1, ButtonChoice.d3: 2}


@dataclass(frozen=True)
class SenderDeps:
    engine: Engine
    whatsapp: WhatsAppOutbound
    gmail_drafts: Callable[[str], GmailDrafts]  # mailbox address → drafts adapter
    template_name: str = "estateos_pending"
    template_language: str = "en"


@dataclass(frozen=True)
class ExecOutcome:
    status: Literal["sent", "already", "blocked", "failed"]
    reason: str | None = None
    provider_ref: str | None = None


def exec_key(action_id: UUID, draft_version: int) -> str:
    return f"exec:{action_id}:{draft_version}"


def _claim(session: Session, company_id: UUID, key: str, action_id: UUID | None, plan: Plan) -> Send:
    session.execute(
        insert(Send)
        .values(
            company_id=company_id, action_id=action_id, idempotency_key=key, channel=plan.channel, target=plan.target
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    return session.execute(select(Send).where(Send.idempotency_key == key).with_for_update()).scalar_one()


def _blocked_reason(session: Session, action: ActionRow, draft_version: int) -> str | None:
    company = session.get(Company, action.company_id)
    if company is None or company.paused:
        return "company paused"
    if action.draft_version != draft_version:
        return "draft version superseded"
    approved = session.scalar(
        select(Approval.id).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    if approved is None:
        return "not approved"
    if action.status not in (ActionStatus.approved, ActionStatus.executed):
        return f"action is {action.status.value}"
    return None


def _variant(session: Session, action: ActionRow, draft_version: int) -> int:
    choice = session.scalar(
        select(Approval.choice).where(
            Approval.company_id == action.company_id,
            Approval.action_id == action.id,
            Approval.draft_version == draft_version,
            Approval.status == ApprovalStatus.approved,
        )
    )
    return _VARIANT.get(choice, 0) if choice else 0


def _deliver(deps: SenderDeps, plan: Plan) -> str:
    if plan.channel is Channel.gmail and plan.draft is not None and plan.mailbox is not None:
        return deps.gmail_drafts(plan.mailbox).create_draft(plan.draft)
    if plan.whatsapp is not None:
        return deps.whatsapp.send(plan.whatsapp)
    raise SendBlockedError("nothing to deliver")


def _mark(engine: Engine, key: str, status: SendStatus, ref: str | None, error: str | None) -> None:
    with Session(engine) as session, session.begin():
        send = session.execute(select(Send).where(Send.idempotency_key == key)).scalar_one()
        send.status, send.provider_ref, send.error = status, ref, error
        send.attempted_at = datetime.now(UTC)
        if send.action_id is not None and status is not SendStatus.pending:
            action = session.get(ActionRow, send.action_id)
            if action is not None:
                action.status = ActionStatus.executed if status is SendStatus.sent else ActionStatus.failed


def execute_action(deps: SenderDeps, action_id: UUID, draft_version: int) -> ExecOutcome:
    key = exec_key(action_id, draft_version)
    with Session(deps.engine) as session, session.begin():
        action = session.scalar(select(ActionRow).where(ActionRow.id == action_id).with_for_update())
        if action is None:
            return ExecOutcome("blocked", "action not found")
        reason = _blocked_reason(session, action, draft_version)
        if reason is not None:
            log.warning("sender.blocked", action_id=str(action_id), reason=reason)
            return ExecOutcome("blocked", reason)
        try:
            plan = plan_for(session, action, _variant(session, action, draft_version), key)
            assert_allowed(session, action.company_id, plan)
        except SendBlockedError as exc:
            log.warning("sender.blocked", action_id=str(action_id), reason=str(exc))
            return ExecOutcome("blocked", str(exc))
        send = _claim(session, action.company_id, key, action.id, plan)
        if send.status is SendStatus.sent:
            return ExecOutcome("already", provider_ref=send.provider_ref)
    return _send(deps, key, plan)


class SendFailedError(EstateOSError):
    """An owner message the provider rejected for good (never retried automatically)."""


def _begin_attempt(engine: Engine, key: str) -> bool:
    """Atomic `pending → sending`: exactly one attempt may call the provider for a send."""
    with Session(engine) as session, session.begin():
        won = session.execute(
            update(Send)
            .where(Send.idempotency_key == key, Send.status == SendStatus.pending)
            .values(status=SendStatus.sending, attempted_at=datetime.now(UTC))
            .returning(Send.id)
        ).first()
    return won is not None


def _send(deps: SenderDeps, key: str, plan: Plan) -> ExecOutcome:
    if not _begin_attempt(deps.engine, key):  # another attempt holds it, or it already finished
        return ExecOutcome("already", reason="another attempt holds this send")
    try:
        ref = _deliver(deps, plan)
    except Exception as exc:
        if getattr(exc, "retryable", False):  # definitely not delivered: free it for the step retry
            _mark(deps.engine, key, SendStatus.pending, None, f"{type(exc).__name__}: {str(exc)[:300]}")
            raise
        prefix = "may have been delivered: " if getattr(exc, "maybe_sent", False) else ""
        reason = f"{prefix}{type(exc).__name__}: {str(exc)[:200]}"
        _mark(deps.engine, key, SendStatus.failed, None, reason)
        return ExecOutcome("failed", reason=reason)
    _mark(deps.engine, key, SendStatus.sent, ref, None)
    return ExecOutcome("sent", provider_ref=ref)


def _direct(deps: SenderDeps, company_id: UUID, key: str, payload: dict[str, Any], to: str) -> str | None:
    plan = Plan(Channel.whatsapp, to, whatsapp=payload)
    with Session(deps.engine) as session, session.begin():
        assert_allowed(session, company_id, plan)
        send = _claim(session, company_id, key, None, plan)
        if send.status is SendStatus.sent:
            return send.provider_ref
    outcome = _send(deps, key, plan)
    if outcome.status == "failed":
        raise SendFailedError(outcome.reason or "owner message rejected")
    return outcome.provider_ref


def _nudge(deps: SenderDeps, company_id: UUID, to: str, last: datetime | None) -> None:
    with Session(deps.engine) as session:
        waiting = len(owner_window.queued(session, company_id))
    template = payloads.template(to, deps.template_name, deps.template_language, [str(waiting)])
    _direct(deps, company_id, owner_window.nudge_key(company_id, last), template, to)


def send_to_owner(deps: SenderDeps, company_id: UUID, key: str, build: Callable[[str], dict[str, Any]]) -> str | None:
    """Owner-channel messages that are not actions (approval cards, briefings, alerts). `build(to)` gets the owner's
    number from the DB. Idempotent per `key`. Returns the provider message id, or None when the WhatsApp 24-hour
    window is closed: then the message waits in the outbox behind one template nudge."""
    with Session(deps.engine) as session, session.begin():
        existing = session.scalar(select(Send).where(Send.idempotency_key == key))
        if existing is not None and existing.status is SendStatus.sent:
            return existing.provider_ref
        to = owner_number(session, company_id)
        payload = build(to)
        assert_allowed(session, company_id, Plan(Channel.whatsapp, to, whatsapp=payload))
        last = owner_window.last_owner_message(session, company_id, to)
        is_open = owner_window.window_open(last, datetime.now(UTC))
        if not is_open:
            owner_window.enqueue(session, company_id, key, payload)
    if not is_open:
        _nudge(deps, company_id, to, last)
        return None
    return _direct(deps, company_id, key, payload, to)


def _settle(deps: SenderDeps, row_id: UUID, status: OutboxStatus) -> None:
    with Session(deps.engine) as session, session.begin():
        row = session.get(OwnerOutbox, row_id)
        if row is not None:
            row.status = status


def flush_owner_outbox(deps: SenderDeps, company_id: UUID) -> int:
    """Harjot wrote: deliver what waited, oldest first, to his *current* number. A message the provider rejects for
    good is cancelled (logged) so it never blocks the rest; a transient error stops the flush and keeps the rest
    queued for the next one. Returns the number delivered."""
    with Session(deps.engine) as session:
        to = owner_number(session, company_id)
        if not owner_window.window_open(owner_window.last_owner_message(session, company_id, to), datetime.now(UTC)):
            return 0
        items = [(row.id, row.idempotency_key, dict(row.payload)) for row in owner_window.queued(session, company_id)]
    delivered = 0
    for row_id, key, payload in items:
        try:
            _direct(deps, company_id, key, {**payload, "to": to.removeprefix("+")}, to)
        except Exception as exc:
            if getattr(exc, "retryable", False):
                break
            log.error("owner.outbox_item_cancelled", key=key, error=type(exc).__name__)
            _settle(deps, row_id, OutboxStatus.cancelled)
            continue
        _settle(deps, row_id, OutboxStatus.sent)
        delivered += 1
    return delivered

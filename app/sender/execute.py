"""The only code path that delivers anything (invariant 5).

`execute_action` re-checks, in one locked transaction: approval approved for this draft version, the action still on
that version, the company not paused, `outbound_mode`, the allowlist (tenant recipient re-derived from the DB), the
hourly tenant send cap and `sends.idempotency_key`. The provider call happens after that commit; a retry finds the
`sends` row and never delivers twice once it is marked sent. A tenant send that is blocked or fails leaves a
dashboard alert saying why.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels.google_chat.render import render_google_chat
from app.channels.whatsapp import payloads
from app.channels.whatsapp.render import render_whatsapp
from app.contracts import (
    ActionType,
    ButtonChoice,
    Channel,
    EmailRequest,
    InteractiveChannel,
    OutboundMode,
    OwnerMessage,
)
from app.core.logging import get_logger
from app.db.enums import ActionStatus, ApprovalStatus, OutboxStatus, SendStatus
from app.db.models import ActionRow, Approval, ChannelAccount, Company, OwnerAccount, OwnerOutbox, Send
from app.sender import owner_window
from app.sender.dashboard import deliver_dashboard
from app.sender.delivery import ExecOutcome as ExecOutcome
from app.sender.delivery import SenderDeps as SenderDeps
from app.sender.delivery import SendFailedError as SendFailedError
from app.sender.delivery import claim, exec_key, send_claimed
from app.sender.targets import (
    Plan,
    SendBlockedError,
    assert_allowed,
    owner_chat_space,
    owner_number,
    plan_for,
)
from app.sender.tenant_gate import tell_owner, tenant_gate

log = get_logger(__name__)
_VARIANT = {ButtonChoice.d2: 1, ButtonChoice.d3: 2}


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


def _plan_checked(
    deps: SenderDeps, session: Session, action: ActionRow, draft_version: int, send_mode: bool, now: datetime
) -> Plan | str:
    """The allowed plan, or why not: pause/version/approval, plan, allowlist, then the send-mode gate (cap)."""
    reason = _blocked_reason(session, action, draft_version)
    if reason is not None:
        return reason
    key = exec_key(action.id, draft_version)
    try:
        variant = _variant(session, action, draft_version)
        plan = plan_for(session, action, variant, key, send_mode=send_mode, now=now)
        assert_allowed(session, action.company_id, plan)
    except SendBlockedError as exc:
        return str(exc)
    gate = tenant_gate(session, action.company_id, key, plan, now, cap=deps.tenant_sends_per_hour,
                       gmail_send_ready=deps.gmail_sender is not None)  # fmt: skip
    return gate if gate is not None else plan


def _prepare(
    deps: SenderDeps, action_id: UUID, draft_version: int, key: str, now: datetime
) -> tuple[Plan | ExecOutcome, UUID | None]:
    """One locked transaction: every re-check, then the claim. Also returns the company to tell if a tenant send
    (send mode, reply_draft) does not go out."""
    with Session(deps.engine) as session, session.begin():
        action = session.scalar(select(ActionRow).where(ActionRow.id == action_id).with_for_update())
        if action is None:
            return ExecOutcome("blocked", "action not found"), None
        mode = session.scalar(select(Company.outbound_mode).where(Company.id == action.company_id))
        send_mode = mode is OutboundMode.send
        tell = action.company_id if send_mode and action.type is ActionType.reply_draft else None
        checked = _plan_checked(deps, session, action, draft_version, send_mode, now)
        if isinstance(checked, str):
            log.warning("sender.blocked", action_id=str(action_id), reason=checked)
            return ExecOutcome("blocked", checked), tell
        send = claim(session, action.company_id, key, action.id, checked)
        if send.status is SendStatus.sent:
            return ExecOutcome("already", provider_ref=send.provider_ref), None
    return checked, tell


def execute_action(deps: SenderDeps, action_id: UUID, draft_version: int) -> ExecOutcome:
    key = exec_key(action_id, draft_version)
    prepared, tell = _prepare(deps, action_id, draft_version, key, datetime.now(UTC))
    outcome = prepared if isinstance(prepared, ExecOutcome) else send_claimed(deps, key, prepared)
    if tell is not None and outcome.status in ("blocked", "failed"):
        tell_owner(deps.engine, tell, action_id, draft_version, outcome.reason)
    return outcome


def _direct(deps: SenderDeps, company_id: UUID, key: str, payload: dict[str, Any], to: str) -> str | None:
    plan = Plan(Channel.whatsapp, to, whatsapp=payload)
    with Session(deps.engine) as session, session.begin():
        assert_allowed(session, company_id, plan)
        send = claim(session, company_id, key, None, plan)
        if send.status is SendStatus.sent:
            return send.provider_ref
    outcome = send_claimed(deps, key, plan)
    if outcome.status == "failed":
        raise SendFailedError(outcome.reason or "owner message rejected")
    return outcome.provider_ref


def _nudge(deps: SenderDeps, company_id: UUID, to: str, last: datetime | None) -> None:
    with Session(deps.engine) as session:
        waiting = len(owner_window.queued(session, company_id))
    template = payloads.template(to, deps.template_name, deps.template_language, [str(waiting)])
    _direct(deps, company_id, owner_window.nudge_key(company_id, last), template, to)


def _direct_chat(deps: SenderDeps, company_id: UUID, key: str, payload: dict[str, Any], space: str) -> str | None:
    plan = Plan(Channel.google_chat, space, google_chat=payload)
    with Session(deps.engine) as session, session.begin():
        assert_allowed(session, company_id, plan)
        send = claim(session, company_id, key, None, plan)
        if send.status is SendStatus.sent:
            return send.provider_ref
    outcome = send_claimed(deps, key, plan)
    if outcome.status == "failed":
        raise SendFailedError(outcome.reason or "owner chat message rejected")
    return outcome.provider_ref


def send_to_owner(
    deps: SenderDeps, company_id: UUID, key: str, build: Callable[[str], dict[str, Any]] | Any
) -> str | None:
    """Owner-channel messages that are not actions (approval cards, briefings, alerts).
    Supports WhatsApp (with 24-hr outbox), Google Chat (instant direct delivery) and the dashboard (one
    idempotent `owner_feed` row, returns the feed id; no window, outbox, Send row or provider call).
    Dashboard feed kind from the key prefix: approval:/apr: approval, doc: document_review, brief/weekly briefing,
    blocked:/nudge:/alert and everything else alert. `ref_id` is the UUID in approval/doc keys.
    """
    with Session(deps.engine) as session:
        existing = session.scalar(select(Send).where(Send.idempotency_key == key))
        if existing is not None and existing.status is SendStatus.sent:
            return existing.provider_ref
        owner = session.scalar(
            select(OwnerAccount).where(OwnerAccount.company_id == company_id).order_by(OwnerAccount.created_at)
        )
        if owner is None:
            raise SendBlockedError("company has no owner account")
        interactive_channel = owner.interactive_channel
        whatsapp_to = owner.whatsapp_e164
        space = None
        if interactive_channel == InteractiveChannel.google_chat:
            space = owner_chat_space(session, company_id)

    if interactive_channel == InteractiveChannel.dashboard:
        return deliver_dashboard(deps.engine, company_id, key, build, whatsapp_to)

    if interactive_channel == InteractiveChannel.google_chat and space is not None:
        if isinstance(build, OwnerMessage):
            payload = render_google_chat(build)
        elif isinstance(build, dict):
            payload = build
        elif callable(build):
            res = build(whatsapp_to)
            if isinstance(res, OwnerMessage):
                payload = render_google_chat(res)
            elif isinstance(res, dict):
                if "text" in res and isinstance(res["text"], dict) and "body" in res["text"]:
                    payload = {"text": str(res["text"]["body"])}
                elif "cardsV2" in res or "text" in res:
                    payload = res
                else:
                    payload = {"text": str(res)}
            else:
                payload = {"text": str(res)}
        else:
            payload = {"text": str(build)}
        return _direct_chat(deps, company_id, key, payload, space)

    to = whatsapp_to
    payload = render_whatsapp(build, to) if isinstance(build, OwnerMessage) else build(to)

    with Session(deps.engine) as session, session.begin():
        assert_allowed(session, company_id, Plan(Channel.whatsapp, to, whatsapp=payload))
        last = owner_window.last_owner_message(session, company_id, to)
        is_open = owner_window.window_open(last, datetime.now(UTC))
        if not is_open:
            owner_window.enqueue(session, company_id, key, payload)
    if not is_open:
        _nudge(deps, company_id, to, last)
        return None
    return _direct(deps, company_id, key, payload, to)


def send_owner_email(deps: SenderDeps, company_id: UUID, key: str, req: EmailRequest) -> str | None:
    """Send an email to the owner (morning digest). Idempotent per `key`."""
    with Session(deps.engine) as session, session.begin():
        existing = session.scalar(select(Send).where(Send.idempotency_key == key))
        if existing is not None and existing.status is SendStatus.sent:
            return existing.provider_ref
        mailbox = session.scalar(
            select(ChannelAccount.address).where(
                ChannelAccount.company_id == company_id,
                ChannelAccount.channel == Channel.gmail,
            )
        )
        if mailbox is None:
            raise SendBlockedError("company has no Gmail mailbox configured to send from")
        plan = Plan(Channel.gmail, req.to, email=req, mailbox=mailbox)
        assert_allowed(session, company_id, plan)
        send = claim(session, company_id, key, None, plan)
        if send.status is SendStatus.sent:
            return send.provider_ref
    outcome = send_claimed(deps, key, plan)
    if outcome.status == "failed":
        raise SendFailedError(outcome.reason or "owner email rejected")
    return outcome.provider_ref


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

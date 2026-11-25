"""Owner-typed WhatsApp sends from the Chats page (ADR 0013): the second allowed send class.

Harjot typed the text and clicked send himself; no AI draft is involved, so there is no approval. Everything else
still holds: the recipient is derived from the DB only (the stored outbound row's `thread_ref`, never a request or
payload value), and every gate runs in the claim transaction: company pause, `outbound_mode=send`, the number
must have written to the company before, must not be one of the company's own numbers, the 23 h window, an own
hourly cap, and `sends.idempotency_key` (`chat:{company_id}:{client_msg_id}`).

The API stores the outbound `messages` row (`delivery_status` NULL) first and enqueues `chat.send_message`;
`send_chat_message` is that workflow's step. A refusal or provider failure marks the row `failed` with
`meta["send_error"]` (a short reason, never the text). An ambiguous provider failure is never retried.
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.channels.whatsapp import payloads
from app.contracts import Channel, Direction, OutboundMode
from app.core.logging import get_logger
from app.core.wa_window import window_open
from app.db.enums import DeliveryStatus, SendStatus
from app.db.models import Company, MessageRow, Send
from app.db.own_addresses import own_addresses
from app.sender.delivery import REUSED_KEY, ExecOutcome, SenderDeps, claim, send_claimed
from app.sender.errors import SendBlockedError
from app.sender.owner_chat_settle import NO_CLIENT_ID, chat_key, mark_row, prior_send, replay, settle
from app.sender.plan import Plan
from app.sender.recipient import canonical
from app.sender.tenant_gate import CAP_WINDOW, CHAT_KEY_PREFIX, cap_reached, owner_targets

log = get_logger(__name__)

PAUSED = "company paused"
SWITCHED_OFF = "sending is switched off for this company"
NO_INBOUND = "no inbound message from this number"
OWN_NUMBER = "this number belongs to the company"
WINDOW_CLOSED = "WhatsApp window closed: the contact wrote more than 23 h ago"
CAP_REACHED = "hourly send cap reached"
NUMBER_CAP_REACHED = "too many messages to this number this hour"
DUPLICATE = "duplicate client message id"
EMPTY = "message is empty"
TOO_LONG = "message is too long"
NOT_FOUND = "message not found"
NO_CAP = 2**31  # `assert_chat` re-checks the gates but not the cap: the claim transaction counted it
_PHONE = re.compile(r"\+[1-9][0-9]{6,14}")
_COUNTED = (SendStatus.pending, SendStatus.sending, SendStatus.sent)


def chat_refusal(
    *,
    paused: bool,
    mode: OutboundMode | None,
    inbound_at: datetime | None,
    company_number: bool,
    now: datetime,
    recent_sends: int,
    cap: int,
    recent_to_number: int,
    number_cap: int,
    text: str,
) -> str | None:
    """Why an owner-typed message may not go out, or None. Pure; gates run in this order.

    `inbound_at` is when the number last wrote to the company (None: never)."""
    if paused:
        return PAUSED
    if mode is not OutboundMode.send:
        return SWITCHED_OFF
    if inbound_at is None:
        return NO_INBOUND
    if company_number:
        return OWN_NUMBER
    if not window_open(inbound_at, now):
        return WINDOW_CLOSED
    if cap_reached(recent_sends, cap):
        return CAP_REACHED
    if cap_reached(recent_to_number, number_cap):
        return NUMBER_CAP_REACHED
    if not text.strip():
        return EMPTY
    if len(text) > payloads.TEXT_BODY_MAX:
        return TOO_LONG
    return None


def contact_number(row: MessageRow) -> str | None:
    """The contact's E.164 number: the stored thread of the row, nothing the request or payload says."""
    number = canonical(row.thread_ref) if row.thread_ref else None
    return number if number is not None and _PHONE.fullmatch(number) else None


def _chat_row(session: Session, company_id: UUID, message_id: UUID) -> MessageRow | None:
    return session.scalar(
        select(MessageRow)
        .where(
            MessageRow.id == message_id,
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.outbound,
        )
        .with_for_update()
    )


def _last_inbound(session: Session, company_id: UUID, number: str) -> datetime | None:
    """The newest receipt of a WhatsApp message from `number` (the older of the two clocks: the conservative anchor)."""
    newest: datetime | None = session.scalar(
        select(func.max(func.least(MessageRow.sent_at, MessageRow.created_at))).where(
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.inbound,
            MessageRow.sender_identity == number,
        )
    )
    return newest


def _recent_chat_sends(session: Session, company_id: UUID, key: str, now: datetime, number: str | None = None) -> int:
    """Owner-typed sends of the company in the last hour (this key excluded), optionally only to one number."""
    where = [
        Send.company_id == company_id,
        Send.idempotency_key.like(f"{CHAT_KEY_PREFIX}%"),
        Send.idempotency_key != key,
        Send.status.in_(_COUNTED),
        Send.created_at > now - CAP_WINDOW,
    ]
    if number is not None:
        where.append(Send.target == number)
    return int(session.scalar(select(func.count()).select_from(Send).where(*where)) or 0)


def _is_company_number(session: Session, company_id: UUID, number: str) -> bool:
    mine = own_addresses(session, company_id) | {c for t in owner_targets(session, company_id) if (c := canonical(t))}
    return number in mine


def gate_reason(
    session: Session, company_id: UUID, row: MessageRow, key: str, now: datetime, deps: SenderDeps | None
) -> str | None:
    """Run every gate against the DB now. `deps=None` skips the caps (the claim transaction already applied them)."""
    company = session.get(Company, company_id)
    number = contact_number(row)
    inbound = _last_inbound(session, company_id, number) if number is not None else None
    return chat_refusal(
        paused=company is None or company.paused,
        mode=company.outbound_mode if company is not None else None,
        inbound_at=inbound,
        company_number=number is not None and _is_company_number(session, company_id, number),
        now=now,
        recent_sends=0 if deps is None else _recent_chat_sends(session, company_id, key, now),
        cap=NO_CAP if deps is None else deps.owner_chat_sends_per_hour,
        recent_to_number=0
        if deps is None or number is None
        else _recent_chat_sends(session, company_id, key, now, number),
        number_cap=NO_CAP if deps is None else deps.owner_chat_sends_per_number_per_hour,
        text=row.text,
    )


def chat_plan(row: MessageRow) -> Plan:
    """The one delivery of a stored row: its own text to its own thread's number."""
    number = contact_number(row)
    if number is None:
        raise SendBlockedError(NO_INBOUND)
    return Plan(Channel.whatsapp, number, whatsapp=payloads.text(number, row.text), chat_message_id=row.id)


def assert_chat(session: Session, company_id: UUID, plan: Plan) -> None:
    """Right before the claim: the plan must be exactly what the stored row says now and every gate must still pass.
    Mirrors `tenant_plans.assert_tenant`; the plan is not trusted."""
    row = session.scalar(
        select(MessageRow).where(
            MessageRow.id == plan.chat_message_id,
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.outbound,
        )
    )
    key = chat_key(company_id, row) if row is not None else None
    if row is None or key is None:
        raise SendBlockedError(NOT_FOUND)
    reason = gate_reason(session, company_id, row, key, datetime.now(UTC), None)
    if reason is None and plan != chat_plan(row):
        reason = "chat plan does not match the stored message"
    if reason is not None:
        raise SendBlockedError(reason)


def _check_unique_and_prior(session: Session, company_id: UUID, row: MessageRow, key: str) -> ExecOutcome | None:
    """Defence in depth behind the unique index on `client_msg_id`: no other row may share the id, and an earlier
    `sends` row under the key must be for this row's own number before it may settle the row."""
    twins = session.scalar(
        select(func.count())
        .select_from(MessageRow)
        .where(
            MessageRow.company_id == company_id,
            MessageRow.channel == Channel.whatsapp,
            MessageRow.direction == Direction.outbound,
            MessageRow.meta["client_msg_id"].as_string() == row.meta["client_msg_id"],
            MessageRow.id != row.id,
        )
    )
    if twins:
        raise SendBlockedError(DUPLICATE)
    send = session.scalar(select(Send).where(Send.company_id == company_id, Send.idempotency_key == key))
    if send is not None and send.target != contact_number(row):
        raise SendBlockedError(REUSED_KEY)
    return prior_send(send)


def _decide(
    session: Session, deps: SenderDeps, company_id: UUID, row: MessageRow, key: str, now: datetime
) -> Plan | ExecOutcome:
    """Earlier attempt under this key, else every gate, else the claim. A refusal settles the row as failed."""
    try:
        prior = _check_unique_and_prior(session, company_id, row, key)
        if prior is not None:
            return prior
        reason = gate_reason(session, company_id, row, key, now, deps)
        if reason is not None:
            raise SendBlockedError(reason)
        plan = chat_plan(row)
        assert_chat(session, company_id, plan)
        claim(session, company_id, key, None, plan)
    except SendBlockedError as exc:
        mark_row(session, company_id, row.id, DeliveryStatus.failed, wamid=None, error=str(exc))
        log.warning("sender.chat_blocked", message_id=str(row.id), reason=str(exc))
        return ExecOutcome("blocked", str(exc))
    return plan


def _prepare(deps: SenderDeps, company_id: UUID, message_id: UUID, now: datetime) -> ExecOutcome | tuple[Plan, str]:
    """One locked transaction (company, then message, then send): replay check, every gate, the claim."""
    with Session(deps.engine) as session, session.begin():
        session.scalar(select(Company).where(Company.id == company_id).with_for_update(key_share=True))
        row = _chat_row(session, company_id, message_id)
        if row is None:
            return ExecOutcome("blocked", NOT_FOUND)
        done, key = replay(row), chat_key(company_id, row)
        if done is not None:
            return done
        if key is None:
            mark_row(session, company_id, row.id, DeliveryStatus.failed, wamid=None, error=NO_CLIENT_ID)
            return ExecOutcome("blocked", NO_CLIENT_ID)
        decided = _decide(session, deps, company_id, row, key, now)
        return decided if isinstance(decided, ExecOutcome) else (decided, key)


def send_chat_message(deps: SenderDeps, company_id: UUID, message_id: UUID) -> ExecOutcome:
    """Deliver one stored owner-typed message (idempotent: a replay never calls the provider again).

    `in_progress` means another attempt holds the send: this run ends and changes nothing. If that attempt died, the
    5-minute sweep (`app.sender.stuck`) settles the send and the row once `STUCK_AFTER` has passed."""
    prepared = _prepare(deps, company_id, message_id, datetime.now(UTC))
    if isinstance(prepared, ExecOutcome):
        outcome = prepared
    else:
        plan, key = prepared
        outcome = send_claimed(deps, key, plan)
    if outcome.status in ("sent", "already", "failed"):
        settle(deps, company_id, message_id, outcome)
    return outcome

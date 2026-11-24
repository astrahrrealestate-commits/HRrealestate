"""Recording what happened to an owner-typed message: the row's delivery status and the `sends` replay rules.

Every write is conditional on the row still being pending (`delivery_status IS NULL`), so a retried step changes
nothing. A reason stored in `meta["send_error"]` is a short sentence, never the message text.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.workflow_names import chat_workflow_id
from app.db.enums import DeliveryStatus, SendStatus
from app.db.models import MessageRow, Send
from app.sender.delivery import STUCK, STUCK_AFTER, ExecOutcome, SenderDeps

_DONE = (DeliveryStatus.sent, DeliveryStatus.delivered, DeliveryStatus.read)


def mark_row(
    session: Session,
    company_id: UUID,
    message_id: UUID,
    status: DeliveryStatus,
    *,
    wamid: str | None,
    error: str | None,
) -> None:
    """Settle a still-pending row once (`delivery_status IS NULL`): the retry of a finished step changes nothing."""
    row = session.scalar(
        select(MessageRow)
        .where(MessageRow.id == message_id, MessageRow.company_id == company_id, MessageRow.delivery_status.is_(None))
        .with_for_update()
    )
    if row is None:
        return
    row.delivery_status = status
    if wamid is not None:
        row.provider_msg_id = wamid
    if error is not None:
        row.meta = {**row.meta, "send_error": error[:300]}


def settle(deps: SenderDeps, company_id: UUID, message_id: UUID, outcome: ExecOutcome) -> None:
    status = DeliveryStatus.sent if outcome.status in ("sent", "already") else DeliveryStatus.failed
    wamid = outcome.provider_ref if status is DeliveryStatus.sent else None
    error = outcome.reason if status is DeliveryStatus.failed else None
    with Session(deps.engine) as session, session.begin():
        mark_row(session, company_id, message_id, status, wamid=wamid, error=error)


def replay(row: MessageRow) -> ExecOutcome | None:
    """A row that already has a final status: report it, change nothing, call nobody."""
    if row.delivery_status is None:
        return None
    if row.delivery_status in _DONE:
        return ExecOutcome("already", provider_ref=row.provider_msg_id)
    return ExecOutcome("failed", reason=str(row.meta.get("send_error") or "send failed"))


def prior_send(send: Send | None) -> ExecOutcome | None:
    """An earlier attempt that finished under this key (a step that died before settling the row)."""
    if send is None:
        return None
    if send.status is SendStatus.sent:
        return ExecOutcome("already", provider_ref=send.provider_ref)
    if send.status is SendStatus.failed:
        return ExecOutcome("failed", reason=send.error or "send failed")
    return None


def settle_stuck_chat(engine: Engine, company_id: UUID, key: str, now: datetime) -> bool:
    """A chat `sending` row older than STUCK_AFTER belongs to an attempt that died mid-call: mark the send and the
    message row failed in one transaction. The conditional UPDATE has one winner; True only for that caller."""
    client = key.split(":", 2)[2] if key.count(":") >= 2 else ""
    with Session(engine) as session, session.begin():
        won = session.execute(
            update(Send)
            .where(
                Send.company_id == company_id,
                Send.idempotency_key == key,
                Send.status == SendStatus.sending,
                (Send.attempted_at.is_(None)) | (Send.attempted_at <= now - STUCK_AFTER),
            )
            .values(status=SendStatus.failed, error=STUCK)
            .returning(Send.id)
        ).first()
        if won is None:
            return False
        message_id = session.scalar(
            select(MessageRow.id).where(
                MessageRow.company_id == company_id,
                MessageRow.channel == Channel.whatsapp,
                MessageRow.direction == Direction.outbound,
                MessageRow.meta["client_msg_id"].as_string() == client,
            )
        )
        if message_id is not None:
            mark_row(session, company_id, message_id, DeliveryStatus.failed, wamid=None, error=STUCK)
    return True


def fail_exhausted(engine: Engine, company_id: UUID, message_id: UUID, reason: str) -> bool:
    """The workflow's step ran out of retries: nobody else will settle the row, so mark it failed with `reason`.

    Only a still-pending row (`delivery_status IS NULL`) whose `sends` row is not `sent` or `sending` is touched: a send
    that went out (or is held by a live attempt) is settled by its own path, never reported as failed here. True only
    when this call marked the row."""
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(MessageRow)
            .where(
                MessageRow.id == message_id,
                MessageRow.company_id == company_id,
                MessageRow.channel == Channel.whatsapp,
                MessageRow.direction == Direction.outbound,
                MessageRow.delivery_status.is_(None),
            )
            .with_for_update()
        )
        if row is None:
            return False
        send = session.scalar(
            select(Send).where(
                Send.company_id == company_id,
                Send.idempotency_key == chat_workflow_id(company_id, row.meta.get("client_msg_id")),
            )
        )
        if send is not None and send.status in (SendStatus.sent, SendStatus.sending):
            return False
        mark_row(session, company_id, message_id, DeliveryStatus.failed, wamid=None, error=reason)
    return True

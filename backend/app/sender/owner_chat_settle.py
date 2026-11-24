"""Recording what happened to an owner-typed message: the row's delivery status and the `sends` replay rules.

Every write is conditional on the row still being pending (`delivery_status IS NULL`), so a retried step changes
nothing. A reason stored in `meta["send_error"]` is a short sentence, never the message text.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.enums import DeliveryStatus, SendStatus
from app.db.models import MessageRow, Send
from app.sender.delivery import STUCK, ExecOutcome, SenderDeps, stuck

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


def settle_stuck(deps: SenderDeps, company_id: UUID, key: str, now: datetime) -> ExecOutcome | None:
    """A `sending` row older than STUCK_AFTER belongs to an attempt that died mid-call: mark it failed, once."""
    with Session(deps.engine) as session, session.begin():
        found = session.execute(
            select(Send.status, Send.attempted_at).where(Send.company_id == company_id, Send.idempotency_key == key)
        ).first()
        if found is None or found[0] is not SendStatus.sending or not stuck(found[1], now):
            return None
        session.execute(
            update(Send)
            .where(Send.company_id == company_id, Send.idempotency_key == key, Send.status == SendStatus.sending)
            .values(status=SendStatus.failed, error=STUCK)
        )
    return ExecOutcome("failed", reason=STUCK)

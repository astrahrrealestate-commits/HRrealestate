"""Owner-channel steps shared by the pipeline and the owner reply workflow: approval cards and exception alerts.

Each WhatsApp message has its own idempotency key (`approval:{id}:{n}`), so a replayed step re-sends nothing.
"""

from uuid import UUID

from dbos import DBOS
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.enums import ActionStatus
from app.db.models import ActionRow, Case
from app.owner.card_data import case_label, load_card
from app.owner.cards import PayloadBuilder, approval_payloads, exception_payload
from app.sender.execute import flush_owner_outbox, send_to_owner
from app.sender.targets import SendBlockedError
from app.workflows.deps import get_engine, get_sender_deps

log = get_logger(__name__)


def _send(company_id: str, key: str, build: PayloadBuilder) -> bool:
    """A blocked owner message (no owner number, allowlist) is logged; the approval stays pending for the briefing."""
    try:
        send_to_owner(get_sender_deps(), UUID(company_id), key, build)
    except SendBlockedError as exc:
        log.error("owner.message_blocked", company_id=company_id, key=key, reason=str(exc))
        return False
    return True


@DBOS.step(name="owner.send_card")
def send_card_step(company_id: str, approval_id: str) -> int:
    with Session(get_engine()) as session:
        card = load_card(session, UUID(company_id), UUID(approval_id))
    sent = [_send(company_id, f"approval:{approval_id}:{n}", b) for n, b in enumerate(approval_payloads(card))]
    return sum(sent)


@DBOS.step(name="owner.alert_exceptions")
def alert_exceptions_step(company_id: str, message_id: str) -> int:
    with Session(get_engine()) as session:
        rows = session.execute(
            select(ActionRow.rationale, Case)
            .join(Case, Case.id == ActionRow.case_id)
            .where(
                ActionRow.company_id == UUID(company_id),
                ActionRow.context_ref.contains([UUID(message_id)]),
                ActionRow.status == ActionStatus.exception,
            )
        ).all()
        if not rows:
            return 0
        label = case_label(session, rows[0][1])
    reason = "Suspicious or out-of-policy message. Nothing was drafted; please handle it yourself."
    _send(company_id, f"exception:{message_id}", exception_payload(label, reason))
    return len(rows)


@DBOS.step(name="owner.flush_outbox")
def flush_outbox_step(company_id: str) -> int:
    """Harjot wrote, so the WhatsApp window is open: deliver what waited while it was closed."""
    return flush_owner_outbox(get_sender_deps(), UUID(company_id))

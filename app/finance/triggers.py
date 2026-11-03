"""When finance work starts (spec 2026-10-31, Flow): the decision-day snapshot on the approval of a request_contractor
action, a quote review for an inbound contractor message that names an amount or carries a file.

The decisions are pure functions; the loaders read only the rows they need. The company always comes from our own row
(action or message), and every further query is scoped to it.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import ActionType, Direction
from app.db.enums import PersonKind
from app.db.models import ActionRow, AttachmentRow, MessageRow, Person, UnderstandingRow


def snapshot_trigger(kind: ActionType) -> bool:
    """Only an approved request_contractor fixes a decision day."""
    return kind is ActionType.request_contractor


def quote_candidate(*, inbound: bool, contractor: bool, amounts: int, attachments: int) -> bool:
    """An inbound message from a contractor with an amount in it, or a file that may be the quote."""
    return inbound and contractor and (amounts > 0 or attachments > 0)


def amounts_in(body: Any) -> int:
    """How many amounts the stored understanding found (0 for a missing or malformed body)."""
    entities = body.get("entities") if isinstance(body, dict) else None
    amounts = entities.get("amounts") if isinstance(entities, dict) else None
    return len(amounts) if isinstance(amounts, list) else 0


def snapshot_company(session: Session, action_id: UUID) -> UUID | None:
    """The company of a request_contractor action (our own id: it gives the company); None for anything else."""
    row = session.execute(select(ActionRow.company_id, ActionRow.type).where(ActionRow.id == action_id)).first()
    return row.company_id if row is not None and snapshot_trigger(row.type) else None


def is_quote_candidate(session: Session, message_id: UUID) -> bool:
    msg = session.scalar(select(MessageRow).where(MessageRow.id == message_id))  # our own id: it gives the company
    if msg is None:
        return False
    cid = msg.company_id
    contractor = msg.person_id is not None and (
        session.scalar(
            select(Person.id).where(
                Person.company_id == cid, Person.id == msg.person_id, Person.kind == PersonKind.contractor
            )
        )
        is not None
    )
    body = session.scalar(
        select(UnderstandingRow.body).where(UnderstandingRow.company_id == cid, UnderstandingRow.message_id == msg.id)
    )
    files = session.scalar(
        select(func.count(AttachmentRow.id)).where(AttachmentRow.company_id == cid, AttachmentRow.message_id == msg.id)
    )
    return quote_candidate(
        inbound=msg.direction is Direction.inbound, contractor=contractor, amounts=amounts_in(body),
        attachments=files or 0,
    )  # fmt: skip

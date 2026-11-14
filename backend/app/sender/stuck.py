"""Tenant sends stuck `sending`: the worker died during the provider call and nobody will report back.

DBOS recovers the same `exec:{action}:{version}` run, but its attempt loses the claim to the dead row and, while that
row is younger than `STUCK_AFTER`, reports `in_progress` and ends. The 5-minute sweep (`sweep.stranded`) then finds
the row once it is older and settles it ONCE through `delivery.give_up_stuck`: a conditional UPDATE (one winner) that
marks the send and the action failed and writes the single alert `blocked:exec:{action}:{version}` in the same
transaction. Fresh rows are never touched (their holder may still report); `resume` skips them either way.

Selection: exec rows (approved actions) on Gmail or WhatsApp whose target is not one of the company's owner numbers or
addresses; company-scoped, paused companies included (settling sends nothing), oldest attempt first, at most `BATCH`
per round across companies.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, Select, func, or_, select
from sqlalchemy.orm import Session

from app.contracts import Channel
from app.db.enums import SendStatus
from app.db.models import Company, Send
from app.sender.delivery import STUCK, STUCK_AFTER, give_up_stuck
from app.sender.tenant_gate import owner_targets

BATCH = 200


@dataclass(frozen=True)
class StuckSend:
    company_id: UUID
    key: str  # the `sends.idempotency_key`, `exec:{action_id}:{draft_version}`
    action_id: UUID
    draft_version: int

    @property
    def alert_key(self) -> str:
        return f"blocked:{self.key}"  # = tenant_gate.blocked_key(action_id, draft_version)


def parse_exec_key(key: str) -> tuple[UUID, int] | None:
    """(action_id, draft_version) of an `exec:{action_id}:{draft_version}` send key, else None."""
    parts = key.split(":")
    if len(parts) != 3 or parts[0] != "exec":
        return None
    try:
        return UUID(parts[1]), int(parts[2])
    except ValueError:
        return None


def candidates(rows: Iterable[tuple[UUID, str, UUID | None]]) -> list[StuckSend]:
    """(company_id, key, action_id) rows whose key is a well-formed exec key naming the row's own action."""
    found: list[StuckSend] = []
    for company_id, key, action_id in rows:
        parsed = parse_exec_key(key)
        if parsed is not None and parsed[0] == action_id:
            found.append(StuckSend(company_id, key, parsed[0], parsed[1]))
    return found


def stuck_query(company_id: UUID, owners: Collection[str], now: datetime, limit: int) -> Select[UUID, str, UUID | None]:
    lowered = sorted({owner.lower() for owner in owners})
    return (
        select(Send.company_id, Send.idempotency_key, Send.action_id)
        .where(
            Send.company_id == company_id,
            Send.status == SendStatus.sending,
            Send.channel.in_((Channel.gmail, Channel.whatsapp)),
            func.lower(Send.target).not_in(lowered),
            Send.idempotency_key.like("exec:%"),
            Send.action_id.is_not(None),
            or_(Send.attempted_at.is_(None), Send.attempted_at <= now - STUCK_AFTER),
        )
        .order_by(Send.attempted_at.asc().nulls_first(), Send.id)
        .limit(limit)
    )


def stuck_for(session: Session, company_id: UUID, now: datetime, limit: int) -> list[StuckSend]:
    rows = session.execute(stuck_query(company_id, owner_targets(session, company_id), now, limit)).all()
    return candidates((row[0], row[1], row[2]) for row in rows)


def stuck_sends(engine: Engine, now: datetime, limit: int = BATCH) -> list[StuckSend]:
    """Per company (every query company-scoped), until `limit` rows in total."""
    found: list[StuckSend] = []
    with Session(engine) as session:
        for company_id in session.scalars(select(Company.id).order_by(Company.id)):
            left = limit - len(found)
            if left <= 0:
                break
            found += stuck_for(session, company_id, now, left)
    return found


def settle(engine: Engine, item: StuckSend, now: datetime) -> bool:
    """True when the send now stands failed as stuck: this call won the give-up, or someone did first (an earlier try
    of this step that died after its commit, or the exec run's own give-up). The owner notice that follows is keyed
    `blocked:exec:{a}:{v}`, so it is still delivered once. False when the row finished any other way."""
    if give_up_stuck(engine, item.key, now, company_id=item.company_id):
        return True
    with Session(engine) as session:
        row = session.execute(
            select(Send.status, Send.error).where(Send.company_id == item.company_id, Send.idempotency_key == item.key)
        ).first()
    return row is not None and row[0] is SendStatus.failed and row[1] == STUCK

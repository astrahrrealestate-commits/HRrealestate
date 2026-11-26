"""Reloaded mail at ingestion (M13): which raw events are history, and the `held` mark that keeps them waiting.

A reload lists the mailbox up to the minute it runs. Mail that arrived within `HISTORY_MARGIN` of being recorded is new
mail, which the live sync may not have reached yet: it goes through the pipeline as usual, drafts included.
"""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Direction, Message
from app.db.enums import PipelineStatus
from app.db.models import MessageRow, RawEvent

HISTORY_MARGIN = timedelta(minutes=15)
HELD = "held"  # the route of a stored history mail: no pipeline run until `run_history`


def is_history_event(payload: dict[str, Any], received_at: datetime, sent_at: datetime) -> bool:
    return payload.get("history") is True and sent_at < received_at - HISTORY_MARGIN


def hold(session: Session, message: Message, message_id: UUID) -> str:
    """Reloaded inbound mail waits for `run_history`. Sent mail has no pipeline run of its own: the history run of its
    thread links and indexes it."""
    if message.direction is Direction.outbound:
        return "none"
    row = session.get(MessageRow, message_id)
    if row is not None:
        row.pipeline_status = PipelineStatus.held
    return HELD


def history_events(engine: Engine, raw_event_ids: list[UUID]) -> set[UUID]:
    """Those of our own raw events that a mailbox reload recorded: their reruns stay off the live queue."""
    with Session(engine) as session:
        rows = session.scalars(
            select(RawEvent.id).where(
                RawEvent.id.in_(raw_event_ids), RawEvent.payload["history"].as_boolean().is_(True)
            )
        )
        return set(rows)

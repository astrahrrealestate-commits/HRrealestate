"""SSE `turn` events: Super Agent turn progress for `/events`.

Cursor scheme: turn frames carry NO `id:` line, so the browser's `Last-Event-ID` stays the feed cursor (unchanged
feed resume). Turns keep their own in-memory cursor `(updated_at, id)` per connection, starting `TURN_REPLAY` before
connect: a (re)connecting client gets the current state of each turn changed in the last 5 minutes once, then every
later change. `GET /agent/conversations/{id}` stays the source of truth after a longer gap.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.schemas import TurnEvent
from app.pipeline.read_turns import TurnCursor, turns_changed_after

TURN_REPLAY = timedelta(minutes=5)


def turn_frame(event: TurnEvent) -> str:
    return f"event: turn\ndata: {event.model_dump_json()}\n\n"


def read_turn_events(engine: Engine, company_id: UUID, owner_id: UUID, after: TurnCursor) -> list[TurnEvent]:
    with Session(engine) as session:
        return [TurnEvent.model_validate(t) for t in turns_changed_after(session, company_id, owner_id, after)]


class TurnPoller:
    """One connection's turn cursor (company + owner scoped). `poll` is sync: run it in a thread."""

    def __init__(self, engine: Engine, company_id: UUID, owner_id: UUID, now: datetime | None = None) -> None:
        self.engine, self.company_id, self.owner_id = engine, company_id, owner_id
        self.after: TurnCursor = ((now or datetime.now(UTC)) - TURN_REPLAY, UUID(int=0))

    def poll(self) -> list[str]:
        events = read_turn_events(self.engine, self.company_id, self.owner_id, self.after)
        if events:
            self.after = (events[-1].updated_at, events[-1].id)
        return [turn_frame(e) for e in events]

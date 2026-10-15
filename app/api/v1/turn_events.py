"""SSE `turn` events: Super Agent turn progress for `/events`.

Cursor scheme: turn frames carry NO `id:` line, so the browser's `Last-Event-ID` stays the feed cursor (unchanged
feed resume). Turns keep their own in-memory cursor `(updated_at, id)` per connection, starting `TURN_REPLAY` before
connect: a (re)connecting client gets the current state of each turn changed in the last 5 minutes once, then every
later change.

Commit skew: `updated_at` is stamped before its transaction commits, so a slow commit can land behind the cursor.
Each poll re-reads an `OVERLAP` window behind the cursor and drops `(turn id, updated_at)` pairs already sent, so a
late commit inside the window is still delivered and nothing is sent twice. A change committed later than that is
missed by the stream: the SPA must re-fetch `GET /agent/conversations/{id}` when a turn it submitted is still
`pending`/`running` after ~30 s (Postgres is the source of truth, SSE only nudges). Edge: more than `MAX_TURN_EVENTS`
changes for one owner inside one overlap window would stall the cursor; one owner never produces that.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.schemas import TurnEvent
from app.pipeline.read_turns import TurnCursor, turns_changed_after

TURN_REPLAY = timedelta(minutes=5)
OVERLAP = timedelta(seconds=2)


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
        self.sent: set[tuple[UUID, datetime]] = set()

    def poll(self) -> list[str]:
        since = (self.after[0] - OVERLAP, UUID(int=0))
        events = read_turn_events(self.engine, self.company_id, self.owner_id, since)
        fresh = [e for e in events if (e.id, e.updated_at) not in self.sent]
        if events:
            self.after = max(self.after, (events[-1].updated_at, events[-1].id))
        self.sent = {k for k in self.sent if k[1] >= self.after[0] - OVERLAP}
        self.sent |= {(e.id, e.updated_at) for e in fresh}
        return [turn_frame(e) for e in fresh]

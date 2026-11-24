"""Shared setup for the owner-chat integration tests: the stored outbound row the API would insert, inbound rows."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.core.workflow_names import chat_workflow_id
from app.db.models import MessageRow, RawEvent, Send
from tests.integration.send_mode_support import OWNER, TENANT_NR, Env

TEXT = "Dag mevrouw, de monteur komt morgen tussen 9 en 11."


@dataclass
class Pending:
    id: UUID
    client_msg_id: UUID

    def key(self, env: Env) -> str:
        return chat_workflow_id(env.company_id, self.client_msg_id)


def add_inbound(env: Env, sender: str, *, company_id: UUID | None = None, age: timedelta = timedelta(hours=1)) -> None:
    cid, at = company_id or env.company_id, datetime.now(UTC) - age
    with Session(env.engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=Channel.whatsapp, provider_msg_id=f"in-{new_id()}", payload={})
        s.add(raw)
        s.flush()
        s.add(MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=Channel.whatsapp, provider_msg_id=raw.provider_msg_id,
            thread_ref=sender, sender_identity=sender, direction=Direction.inbound, sent_at=at, created_at=at,
            text="Hallo",
        ))  # fmt: skip


def pending_row(
    env: Env, thread: str = TENANT_NR, text: str = TEXT, *, client_msg_id: UUID | None = None, **meta: Any
) -> Pending:
    """What the API stores before it enqueues: an outbound row with no delivery status yet."""
    client = client_msg_id or new_id()
    with Session(env.engine) as s, s.begin():
        raw = RawEvent(
            company_id=env.company_id, provider=Channel.whatsapp, provider_msg_id=f"o-{new_id()}", payload={}
        )
        s.add(raw)
        s.flush()
        row = MessageRow(
            company_id=env.company_id,
            raw_event_id=raw.id,
            channel=Channel.whatsapp,
            provider_msg_id=f"pending:{new_id()}",
            thread_ref=thread,
            sender_identity=OWNER,
            direction=Direction.outbound,
            sent_at=datetime.now(UTC),
            text=text,
            meta={"client_msg_id": str(client), **meta},
        )
        s.add(row)
        s.flush()
        return Pending(row.id, client)


def row_of(env: Env, message_id: UUID) -> MessageRow:
    with Session(env.engine) as s:
        return s.scalars(select(MessageRow).where(MessageRow.id == message_id)).one()


def send_of(env: Env, key: str) -> Send | None:
    with Session(env.engine) as s:
        return s.scalar(select(Send).where(Send.company_id == env.company_id, Send.idempotency_key == key))


def all_sends(env: Env) -> int:
    with Session(env.engine) as s:
        return len(list(s.scalars(select(Send.id).where(Send.company_id == env.company_id))))

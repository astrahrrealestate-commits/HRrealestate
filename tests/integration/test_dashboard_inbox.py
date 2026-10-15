"""Inbox and thread endpoints against real Postgres: scoping, ordering, counts, clamp, presigned TTL."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.db.enums import DeliveryStatus, PipelineStatus
from app.db.models import Company, OwnerAccount
from app.db.models.ingestion import AttachmentRow, MessageRow, RawEvent
from app.main import create_app
from app.pipeline.read_repo import encode_thread_key
from app.storage.memory import MemoryStorage

pytestmark = pytest.mark.integration
T0 = datetime(2026, 1, 1, tzinfo=UTC)
GMAIL_REF = "<thread-1@mail.gmail.com>"


@dataclass
class World:
    client: TestClient
    key_a_gmail: str
    key_a_wa: str
    key_b: str


def _msg(s: Session, cid: UUID, channel: Channel, pid: str, ref: str | None, n: int, **kw: object) -> MessageRow:
    raw = RawEvent(company_id=cid, provider=channel, provider_msg_id=pid, payload={})
    s.add(raw)
    s.flush()
    row = MessageRow(
        company_id=cid, raw_event_id=raw.id, channel=channel, provider_msg_id=pid, thread_ref=ref,
        sender_identity="x@y.test", direction=kw.pop("direction", Direction.inbound),
        sent_at=T0 + timedelta(minutes=n), text=f"m{n}", **kw,
    )  # fmt: skip
    s.add(row)
    s.flush()
    return row


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    storage = MemoryStorage()
    with Session(migrated_engine) as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.flush()
        owner = OwnerAccount(company_id=a.id, display_name="H", whatsapp_e164="+31699999998", email="h@a.test")
        s.add(owner)
        _msg(s, a.id, Channel.gmail, "g1", GMAIL_REF, 1, pipeline_status=PipelineStatus.pending)
        _msg(s, a.id, Channel.gmail, "g2", GMAIL_REF, 2, direction=Direction.outbound,
             delivery_status=DeliveryStatus.sent, pipeline_status=PipelineStatus.done)  # fmt: skip
        wa = _msg(s, a.id, Channel.whatsapp, "w1", None, 3, meta={"suspicious": True})
        s.add(AttachmentRow(company_id=a.id, message_id=wa.id, s3_key="media/a/ab/abc", mime_type="image/jpeg",
                            filename="p.jpg", size_bytes=3, sha256="ab" * 32))  # fmt: skip
        _msg(s, b.id, Channel.gmail, "bg1", "<b-thread>", 1)
        s.commit()
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        settings = Settings(  # type: ignore[call-arg]
            database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32), _env_file=None
        )
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock(), storage=storage)
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield World(
                client,
                encode_thread_key(Channel.gmail, GMAIL_REF),
                encode_thread_key(Channel.whatsapp, "w1"),
                encode_thread_key(Channel.gmail, "<b-thread>"),
            )
        ids = [a.id, b.id]
        for model in (AttachmentRow, MessageRow, RawEvent):
            s.query(model).filter(model.company_id.in_(ids)).delete(synchronize_session=False)
        s.query(OwnerAccount).filter(OwnerAccount.id == owner.id).delete()
        s.query(Company).filter(Company.id.in_(ids)).delete()
        s.commit()


def test_inbox_lists_own_threads_newest_first_with_counts(world: World) -> None:
    body = world.client.get("/api/v1/inbox").json()
    assert [t["thread_key"] for t in body] == [world.key_a_wa, world.key_a_gmail]
    assert [t["message_count"] for t in body] == [1, 2]
    assert body[1]["last_text"] == "m2"
    assert body[1]["unread_pipeline"] == "pending"  # held inbound message is never hidden


def test_inbox_before_cursor_pages(world: World) -> None:
    first = world.client.get("/api/v1/inbox", params={"limit": 1}).json()
    second = world.client.get("/api/v1/inbox", params={"limit": 1, "before": first[0]["cursor"]}).json()
    assert [t["thread_key"] for t in second] == [world.key_a_gmail]


def test_limit_is_clamped(world: World) -> None:
    assert world.client.get("/api/v1/inbox", params={"limit": 1000}).status_code == 200


def test_foreign_and_own_keys(world: World) -> None:
    assert world.client.get(f"/api/v1/threads/{world.key_b}").status_code == 404
    assert world.client.get("/api/v1/threads/not-a-key").status_code == 404
    own = world.client.get(f"/api/v1/threads/{world.key_a_gmail}")
    assert own.status_code == 200
    assert [m["direction"] for m in own.json()] == ["inbound", "outbound"]
    assert own.json()[1]["delivery_status"] == "sent"
    assert own.json()[0]["pipeline_status"] == "pending"


def test_attachment_url_and_suspicious_hint(world: World) -> None:
    msg = world.client.get(f"/api/v1/threads/{world.key_a_wa}").json()[0]
    assert msg["suspicious"] is True
    url = msg["attachments"][0]["url"]
    assert int(parse_qs(urlparse(url).query)["expires_in"][0]) <= 300

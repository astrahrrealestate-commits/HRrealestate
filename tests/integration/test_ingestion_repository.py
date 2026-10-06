import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from dbos import DBOSClient
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction, Message
from app.core.errors import NotFoundError, TenantMismatchError
from app.core.workflow_names import PROCESS_EVENT, event_workflow_id
from app.db.enums import DeliveryStatus, RawEventStatus
from app.db.models import AttachmentRow, ChannelAccount, Company, MessageRow, RawEvent
from app.ingestion.media import AttachmentInput, store_attachment
from app.ingestion.repository import (
    apply_status,
    mark_raw_event,
    record_event,
    record_status,
    resolve_channel_account,
    save_message,
)
from app.storage.memory import MemoryStorage

pytestmark = pytest.mark.integration
PNID = "100000000000001"


@pytest.fixture
def account(db: Session, company: Company) -> ChannelAccount:
    acc = ChannelAccount(company_id=company.id, channel=Channel.whatsapp, address=PNID)
    db.add(acc)
    db.flush()
    return acc


def _other_account(db: Session) -> ChannelAccount:
    other = Company(name="Other GmbH")
    db.add(other)
    db.flush()
    acc = ChannelAccount(company_id=other.id, channel=Channel.whatsapp, address=f"pn-{uuid4().hex[:8]}")
    db.add(acc)
    db.flush()
    return acc


def _message(raw_event_id: UUID, company_id: UUID, wamid: str = "wamid.T1") -> Message:
    return Message(
        channel=Channel.whatsapp,
        provider_msg_id=wamid,
        thread_ref="+4915550000001",
        sender_identity="+4915550000001",
        direction=Direction.outbound,
        sent_at=datetime(2026, 1, 1, tzinfo=UTC),
        text="Hallo",
        raw_event_id=raw_event_id,
        company_id=company_id,
    )


def _saved(db: Session, client: DBOSClient, acc: ChannelAccount, wamid: str) -> UUID:
    rid = record_event(db, client, acc, wamid, {})
    assert rid is not None
    mid, created = save_message(db, _message(rid, acc.company_id, wamid), {}, [])
    assert created
    return mid


def _workflows(db: Session, workflow_id: str) -> list[tuple[str, str]]:
    """Read DBOS's queue inside the test transaction (a separate client connection cannot see uncommitted rows)."""
    rows = db.execute(
        text("SELECT name, status FROM dbos.workflow_status WHERE workflow_uuid = :id"), {"id": workflow_id}
    ).all()
    return [(r.name, r.status) for r in rows]


def test_resolve_channel_account(db: Session, account: ChannelAccount) -> None:
    assert resolve_channel_account(db, Channel.whatsapp, PNID).id == account.id
    with pytest.raises(NotFoundError):
        resolve_channel_account(db, Channel.whatsapp, "999")


def test_record_event_once_with_one_workflow(dbos_client: DBOSClient, db: Session, account: ChannelAccount) -> None:
    first = record_event(db, dbos_client, account, "wamid.T1", {"a": 1})
    assert record_event(db, dbos_client, account, "wamid.T1", {"a": 1}) is None
    assert first is not None
    rows = db.scalars(select(RawEvent).where(RawEvent.provider_msg_id == "wamid.T1")).all()
    assert [r.company_id for r in rows] == [account.company_id]
    assert _workflows(db, event_workflow_id(first)) == [(PROCESS_EVENT, "ENQUEUED")]


def test_same_provider_id_in_two_companies_is_not_a_duplicate(
    dbos_client: DBOSClient, db: Session, account: ChannelAccount
) -> None:
    other = _other_account(db)
    assert record_event(db, dbos_client, account, "18c0000000000001", {}) is not None
    assert record_event(db, dbos_client, other, "18c0000000000001", {}) is not None


def test_save_message_idempotent_returns_existing_id(
    dbos_client: DBOSClient, db: Session, account: ChannelAccount
) -> None:
    rid = record_event(db, dbos_client, account, "wamid.T1", {})
    assert rid is not None
    att = store_attachment(MemoryStorage(), account.company_id, b"\xff\xd8jpeg", "image/jpeg", "foto.jpg")
    mid, created = save_message(db, _message(rid, account.company_id), {"type": "image"}, [att])
    again, created_again = save_message(db, _message(rid, account.company_id), {"type": "image"}, [att])
    assert (created, created_again, again) == (True, False, mid)
    row = db.get(MessageRow, mid)
    assert row is not None
    assert row.meta == {"type": "image"}
    [stored] = db.scalars(select(AttachmentRow).where(AttachmentRow.message_id == mid)).all()
    assert (stored.filename, stored.mime_type, stored.size_bytes) == ("foto.jpg", "image/jpeg", 6)
    assert stored.s3_key.startswith(f"media/{account.company_id}/")


def test_tenant_guards(dbos_client: DBOSClient, db: Session, account: ChannelAccount) -> None:
    rid = record_event(db, dbos_client, account, "wamid.T1", {})
    assert rid is not None
    other = _other_account(db)
    with pytest.raises(NotFoundError):  # raw event is not visible from another company
        save_message(db, _message(rid, other.company_id), {}, [])
    foreign = AttachmentInput(f"media/{other.company_id}/aa/{'a' * 64}", "image/jpeg", "x.jpg", 1, "a" * 64)
    with pytest.raises(TenantMismatchError):
        save_message(db, _message(rid, account.company_id), {}, [foreign])
    with pytest.raises(NotFoundError):
        mark_raw_event(db, other.company_id, rid, RawEventStatus.failed)


def test_statuses_are_company_scoped(dbos_client: DBOSClient, db: Session, account: ChannelAccount) -> None:
    mine = _saved(db, dbos_client, account, "wamid.SHARED")
    other = _other_account(db)
    record_status(db, other, "wamid.SHARED", DeliveryStatus.read, {})
    assert apply_status(db, other.company_id, "wamid.SHARED", DeliveryStatus.failed) is False
    row = db.get(MessageRow, mine)
    assert row is not None
    assert row.delivery_status is None


def test_status_moves_forward_only_and_replays_late(
    dbos_client: DBOSClient, db: Session, account: ChannelAccount
) -> None:
    for status in (DeliveryStatus.read, DeliveryStatus.delivered):  # before the message exists, out of order
        assert record_status(db, account, "wamid.OUT1", status, {}) is False
    record_status(db, account, "wamid.OUT10", DeliveryStatus.failed, {})  # sibling id must not match
    mid = _saved(db, dbos_client, account, "wamid.OUT1")
    row = db.get(MessageRow, mid)
    assert row is not None
    assert row.delivery_status is DeliveryStatus.read
    assert apply_status(db, account.company_id, "wamid.OUT1", DeliveryStatus.delivered) is False
    assert apply_status(db, account.company_id, "wamid.OUT1", DeliveryStatus.failed) is True
    db.refresh(row)
    assert row.delivery_status is DeliveryStatus.failed


def test_mark_raw_event(dbos_client: DBOSClient, db: Session, account: ChannelAccount) -> None:
    rid = record_event(db, dbos_client, account, "wamid.T9", {})
    assert rid is not None
    mark_raw_event(db, account.company_id, rid, RawEventStatus.failed, error="x" * 5000)
    raw = db.get(RawEvent, rid)
    assert raw is not None
    assert (raw.status, raw.attempts) == (RawEventStatus.failed, 1)
    assert raw.last_error is not None
    assert len(raw.last_error) == 2000


# ---- committed-transaction tests (own company, cleaned up) ----------------------------------------------------------


@pytest.fixture
def committed_account(dbos_client: DBOSClient, migrated_engine: Engine) -> Iterator[ChannelAccount]:
    with Session(migrated_engine, expire_on_commit=False) as session:
        company = Company(name="Committed GmbH")
        session.add(company)
        session.flush()
        acc = ChannelAccount(company_id=company.id, channel=Channel.whatsapp, address=f"pn-{uuid4().hex}")
        session.add(acc)
        session.commit()
        session.expunge(acc)
    yield acc
    with Session(migrated_engine) as session:
        for model in (AttachmentRow, MessageRow, RawEvent, ChannelAccount):
            session.execute(delete(model).where(model.company_id == acc.company_id))
        session.execute(delete(Company).where(Company.id == acc.company_id))
        session.commit()


def test_enqueue_commits_and_rolls_back_with_the_row(
    dbos_client: DBOSClient, migrated_engine: Engine, committed_account: ChannelAccount
) -> None:
    """Postgres before work: no workflow without its committed raw event, and vice versa."""
    with Session(migrated_engine) as session:
        rolled = record_event(session, dbos_client, committed_account, f"wamid.RB{uuid4().hex}", {})
        session.rollback()
        kept = record_event(session, dbos_client, committed_account, f"wamid.OK{uuid4().hex}", {})
        session.commit()
    assert dbos_client.list_workflows(workflow_ids=[event_workflow_id(rolled)]) == []
    assert [w.status for w in dbos_client.list_workflows(workflow_ids=[event_workflow_id(kept)])] == ["ENQUEUED"]


def test_concurrent_status_and_message_never_lose_the_status(
    dbos_client: DBOSClient, migrated_engine: Engine, committed_account: ChannelAccount
) -> None:
    """T1 records a status and holds its transaction; T2 saves the message meanwhile. The lock makes T2 see T1."""
    wamid = f"wamid.RACE{uuid4().hex}"
    status_recorded = threading.Event()

    def status_transaction() -> None:
        with Session(migrated_engine) as s1:
            record_status(s1, committed_account, wamid, DeliveryStatus.read, {})
            status_recorded.set()
            time.sleep(0.5)  # hold the lock while the message transaction starts
            s1.commit()

    thread = threading.Thread(target=status_transaction)
    thread.start()
    assert status_recorded.wait(5)
    with Session(migrated_engine) as s2:
        rid = record_event(s2, dbos_client, committed_account, wamid, {})
        assert rid is not None
        mid, _ = save_message(s2, _message(rid, committed_account.company_id, wamid), {}, [])
        s2.commit()
    thread.join()
    with Session(migrated_engine) as s3:
        row = s3.get(MessageRow, mid)
        assert row is not None
        assert row.delivery_status is DeliveryStatus.read

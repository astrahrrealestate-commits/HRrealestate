"""BRIXX document downloads against Postgres: idempotent store and replay, forbidden, claims, candidates, backlog."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi
from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError
from app.db.enums import BrixxDocumentStatus as Status
from app.db.models import Company
from app.db.models.brixx import BrixxDocument
from app.directory.brixx.document_candidates import candidates_query
from app.directory.brixx.document_state import MAX_ATTEMPTS, backlog_counts, claim_versions, record_unstored
from app.directory.brixx.documents import document_key, download_version
from app.directory.brixx.upsert import upsert_page
from app.storage.memory import MemoryStorage
from tests.integration.brixx_support import mirror_schema

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.7 lease scan"
SHA = hashlib.sha256(PDF).hexdigest()
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def document_info() -> BrixxTable:
    return BrixxTable(
        "PRG_DOCUMENT",
        "PRG_DOCUMENTID",
        (
            BrixxField(1, "PRG_DOCUMENTID", "NUMBER", True, None, None),
            BrixxField(2, "VERSIENR", "NUMBER", False, None, None),
            BrixxField(3, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
        ),
    )


@pytest.fixture
def cid(committed_company: Company) -> uuid.UUID:
    return committed_company.id


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        yield s


def _rows(session: Session, company_id: uuid.UUID) -> list[BrixxDocument]:
    session.expire_all()
    query = sa.select(BrixxDocument).where(BrixxDocument.company_id == company_id).order_by(BrixxDocument.created_at)
    return list(session.scalars(query))


def test_download_stores_once_and_a_replay_downloads_nothing(session: Session, cid: uuid.UUID) -> None:
    api, storage = FakeBrixxApi({}, documents={7: PDF}), MemoryStorage()
    claim_versions(session, cid, [(7, "v1")])
    session.commit()

    assert download_version(session, api, storage, cid, 7, "v1") is Status.stored
    assert download_version(session, api, storage, cid, 7, "v1") is Status.stored  # DBOS retried after the commit

    [row] = _rows(session, cid)
    assert (row.status, row.sha256, row.size_bytes, row.attempts) == (Status.stored, SHA, len(PDF), 1)
    assert row.storage_key == document_key(cid, 7, SHA)
    assert storage.get(row.storage_key) == PDF
    assert api.download_log == [7]


def test_new_version_with_the_same_bytes_keeps_one_row_and_one_object(session: Session, cid: uuid.UUID) -> None:
    api, storage = FakeBrixxApi({}, documents={7: PDF}), MemoryStorage()
    claim_versions(session, cid, [(7, "v1")])
    session.commit()
    download_version(session, api, storage, cid, 7, "v1")
    claim_versions(session, cid, [(7, "v2")])
    session.commit()

    assert download_version(session, api, storage, cid, 7, "v2") is Status.stored

    [row] = _rows(session, cid)
    assert (row.source_version, row.sha256, row.status) == ("v2", SHA, Status.stored)


def test_new_bytes_add_a_row_and_keep_the_old_object(session: Session, cid: uuid.UUID) -> None:
    storage = MemoryStorage()
    download_version(session, FakeBrixxApi({}, documents={7: PDF}), storage, cid, 7, "v1")
    download_version(session, FakeBrixxApi({}, documents={7: PDF + b"2"}), storage, cid, 7, "v2")

    rows = _rows(session, cid)
    assert [(r.source_version, r.status) for r in rows] == [("v1", Status.stored), ("v2", Status.stored)]
    assert all(storage.exists(r.storage_key or "") for r in rows)


def test_forbidden_is_recorded_and_not_downloaded_again(session: Session, cid: uuid.UUID) -> None:
    api, storage = FakeBrixxApi({}, documents={7: PDF}), MemoryStorage()
    api.fail_download(7, BrixxAuthError("BRIXX rejected the token (HTTP 403)"), once=False)
    claim_versions(session, cid, [(7, "v1")])
    session.commit()

    assert download_version(session, api, storage, cid, 7, "v1") is Status.forbidden
    assert download_version(session, api, storage, cid, 7, "v1") is Status.forbidden

    [row] = _rows(session, cid)
    assert (row.status, row.last_error, row.sha256) == (Status.forbidden, "BrixxAuthError", None)
    assert api.download_log == [7]
    assert claim_versions(session, cid, [(7, "v1")]) == []  # settled: never claimed again


def test_other_errors_propagate_and_record_nothing(session: Session, cid: uuid.UUID) -> None:
    api = FakeBrixxApi({}, documents={})  # unknown document: BrixxError, retried by the DBOS step
    claim_versions(session, cid, [(7, "v1")])
    session.commit()
    with pytest.raises(BrixxError):
        download_version(session, api, MemoryStorage(), cid, 7, "v1")
    [row] = _rows(session, cid)
    assert row.status is Status.pending


def test_claims_retry_failed_versions_until_max_attempts(session: Session, cid: uuid.UUID) -> None:
    [first] = claim_versions(session, cid, [(7, "v1")])
    assert first.attempt == 1
    assert [c.attempt for c in claim_versions(session, cid, [(7, "v1")])] == [1]  # still pending: same workflow id
    for attempt in range(2, MAX_ATTEMPTS + 1):
        record_unstored(session, cid, 7, "v1", Status.failed, "BrixxError")
        assert [c.attempt for c in claim_versions(session, cid, [(7, "v1")])] == [attempt]
    record_unstored(session, cid, 7, "v1", Status.failed, "BrixxError")
    assert claim_versions(session, cid, [(7, "v1")]) == []
    session.commit()


def test_a_stored_version_is_never_downgraded(session: Session, cid: uuid.UUID) -> None:
    download_version(session, FakeBrixxApi({}, documents={7: PDF}), MemoryStorage(), cid, 7, "v1")
    record_unstored(session, cid, 7, "v1", Status.failed, "BrixxError")
    session.commit()
    assert [r.status for r in _rows(session, cid)] == [Status.stored]


def test_backlog_counts_are_per_company(session: Session, cid: uuid.UUID) -> None:
    claim_versions(session, cid, [(1, "v1"), (2, "v1"), (3, "v1")])
    record_unstored(session, cid, 2, "v1", Status.forbidden, "BrixxAuthError")
    session.commit()
    download_version(session, FakeBrixxApi({}, documents={3: PDF}), MemoryStorage(), cid, 3, "v1")

    assert backlog_counts(session, cid) == {Status.pending: 1, Status.stored: 1, Status.forbidden: 1, Status.failed: 0}
    assert set(backlog_counts(session, uuid.uuid4()).values()) == {0}


def test_candidates_are_live_unsettled_versions_of_this_company(cid: uuid.UUID, migrated_engine: Engine) -> None:
    info = document_info()
    with mirror_schema(migrated_engine) as mirror:
        table = mirror.create(info)
        with mirror.session() as m:
            rows: list[dict[str, object]] = [
                {"PRG_DOCUMENTID": i, "VERSIENR": 1, "UPDDATETIME": "2026-10-21T09:00:00"} for i in (1, 2, 3)
            ]
            upsert_page(m, table, info, cid, rows, NOW)
            m.execute(sa.update(table).where(table.c.prg_documentid == 3).values(_deleted_at=NOW))
            m.commit()
            found = m.execute(candidates_query(table, cid, 10)).all()
            assert [doc for doc, _v in found] == [1, 2]
            version = found[0][1]
            assert version.startswith("v1|u2026-10-21T")  # versienr and upddatetime (rendered in UTC)

            claim_versions(m, cid, [(1, version)])
            m.commit()
            assert [doc for doc, _v in m.execute(candidates_query(table, cid, 10))] == [1, 2]  # pending: still listed
            download_version(m, FakeBrixxApi({}, documents={1: PDF}), MemoryStorage(), cid, 1, version)
            assert [doc for doc, _v in m.execute(candidates_query(table, cid, 10))] == [2]

            upsert_page(m, table, info, cid, [{**rows[0], "VERSIENR": 2}], NOW)
            m.commit()
            assert [doc for doc, _v in m.execute(candidates_query(table, cid, 10))] == [1, 2]  # changed: again
            assert m.execute(candidates_query(table, uuid.uuid4(), 10)).all() == []

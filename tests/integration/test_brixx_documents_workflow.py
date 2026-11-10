"""PRG_DOCUMENT sync → document download workflows: real DBOS executor and Postgres, FakeBrixxApi, MemoryStorage."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from dbos import DBOS
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError
from app.core.workflow_names import BRIXX_DOWNLOAD_DOCUMENT
from app.db.enums import BrixxDocumentStatus as Status
from app.db.enums import BrixxRunStatus
from app.db.models import Company
from app.db.models.brixx import BrixxDocument, BrixxSyncRun
from app.ingestion.process import IngestDeps
from app.storage.memory import MemoryStorage
from app.workflows import brixx_sync
from app.workflows.deps import set_brixx_api, set_deps, set_engine
from tests.integration.brixx_support import MirrorSchema, mirror_schema

pytestmark = pytest.mark.integration

SCHEDULED = datetime(2026, 11, 3, 8, 15, tzinfo=UTC)
FILES = {1: b"%PDF lease", 2: b"%PDF passport", 3: b"\xff\xd8 photo"}
INFO = BrixxTable(
    "PRG_DOCUMENT",
    "PRG_DOCUMENTID",
    (
        BrixxField(1, "PRG_DOCUMENTID", "NUMBER", True, None, None),
        BrixxField(2, "VERSIENR", "NUMBER", False, None, None),
        BrixxField(3, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
    ),
)


class Env:
    def __init__(self, mirror: MirrorSchema, company_id: Any, storage: MemoryStorage) -> None:
        self.mirror, self.company_id, self.storage = mirror, company_id, storage
        mirror.create(INFO)
        rows: list[dict[str, object]] = [
            {"PRG_DOCUMENTID": i, "VERSIENR": 1, "UPDDATETIME": "2026-10-21T09:00:00"} for i in FILES
        ]
        self.api = FakeBrixxApi({"PRG_DOCUMENT": FakeTable(INFO, rows)}, documents=dict(FILES))
        set_brixx_api(self.api)

    def documents(self) -> dict[int, BrixxDocument]:
        with Session(self.mirror.engine, expire_on_commit=False) as s:
            found = s.scalars(sa.select(BrixxDocument).where(BrixxDocument.company_id == self.company_id))
            return {d.document_id: d for d in found}

    def run_status(self) -> list[BrixxRunStatus]:
        with Session(self.mirror.engine) as s:
            query = sa.select(BrixxSyncRun.status).where(BrixxSyncRun.company_id == self.company_id)
            return list(s.scalars(query.order_by(BrixxSyncRun.started_at)))


def _drain() -> list[str]:
    """Wait for every download workflow (they are enqueued by the table child, which does not wait for them)."""
    started = DBOS.list_workflows(name=BRIXX_DOWNLOAD_DOCUMENT)
    handles: list[Any] = [DBOS.retrieve_workflow(w.workflow_id) for w in started]
    return sorted(str(h.get_result()) for h in handles)


@pytest.fixture
def env(dbos_runtime: None, migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    storage = MemoryStorage()
    with mirror_schema(migrated_engine) as mirror:
        set_engine(mirror.engine)
        set_deps(IngestDeps(mirror.engine, storage, cast(Any, None), lambda a: None, lambda p: None, "t"))  # type: ignore[arg-type, return-value]
        yield Env(mirror, committed_company.id, storage)
    set_deps(None)
    set_brixx_api(None)


def test_sync_downloads_every_document_once(env: Env) -> None:
    brixx_sync.sync_all(SCHEDULED, None)
    assert _drain() == ["stored", "stored", "stored"]

    docs = env.documents()
    assert {d: r.status for d, r in docs.items()} == dict.fromkeys(FILES, Status.stored)
    for document_id, data in FILES.items():
        assert env.storage.get(docs[document_id].storage_key or "") == data
    assert env.run_status() == [BrixxRunStatus.succeeded]

    brixx_sync.sync_all(SCHEDULED.replace(minute=30), None)  # next tick: unchanged rows are settled
    _drain()
    assert sorted(env.api.download_log) == [1, 2, 3]
    assert len(env.documents()) == 3


def test_forbidden_document_is_surfaced_and_not_retried(env: Env) -> None:
    env.api.fail_download(2, BrixxAuthError("BRIXX rejected the token (HTTP 403)"), once=False)

    brixx_sync.sync_all(SCHEDULED, None)
    assert _drain() == ["forbidden", "stored", "stored"]
    brixx_sync.sync_all(SCHEDULED.replace(minute=30), None)
    _drain()

    forbidden = env.documents()[2]
    assert (forbidden.status, forbidden.last_error) == (Status.forbidden, "BrixxAuthError")
    assert env.api.download_log.count(2) == 1


def test_repeated_tick_enqueues_no_second_download(env: Env) -> None:
    brixx_sync.sync_all(SCHEDULED, None)
    _drain()
    brixx_sync.sync_all(SCHEDULED, None)  # the same cron tick delivered again
    assert len(_drain()) == 3
    assert sorted(env.api.download_log) == [1, 2, 3]

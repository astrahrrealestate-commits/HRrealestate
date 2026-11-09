"""Daily BRIXX reconcile end to end: real DBOS and Postgres, FakeBrixxApi, throwaway mirror schema, invented rows."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.db.enums import BrixxRunKind, BrixxRunStatus
from app.db.models import Company
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState
from app.db.models.brixx_directory import BrixxReconcileSeen
from app.directory.brixx.state import get_or_create_table_state
from app.directory.brixx.upsert import upsert_page
from app.workflows import brixx_reconcile
from app.workflows.deps import set_brixx_api
from tests.integration.brixx_directory_support import OBJECT, obj
from tests.integration.brixx_support import MirrorSchema, mirror_schema

pytestmark = pytest.mark.integration

TICK = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)
SYNCED = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
WATERMARK = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)


class Env:
    def __init__(self, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
        self.mirror = mirror
        self.company_id = company_id
        self.table = mirror.create(OBJECT)
        self.api = FakeBrixxApi({})

    def seed_mirror(self, rows: list[dict[str, object]], synced_at: datetime = SYNCED) -> None:
        with self.mirror.session() as s:
            upsert_page(s, self.table, OBJECT, self.company_id, rows, synced_at)
            state = get_or_create_table_state(s, self.company_id, OBJECT.name)
            state.last_success_upd = WATERMARK
            s.commit()

    def brixx_has(self, rows: list[dict[str, object]], page_size: int = 2) -> None:
        self.api = FakeBrixxApi({OBJECT.name: FakeTable(OBJECT, rows)}, page_size=page_size)
        set_brixx_api(self.api)

    def mirror_rows(self) -> dict[int, sa.Row[tuple[object, ...]]]:
        with self.mirror.session() as s:
            found = s.execute(sa.select(self.table).where(self.table.c.company_id == self.company_id))
            return {row.prg_objectid: row for row in found}

    def runs(self) -> list[BrixxSyncRun]:
        with Session(self.mirror.engine) as s:
            return list(s.scalars(sa.select(BrixxSyncRun).where(BrixxSyncRun.company_id == self.company_id)))

    def state(self) -> BrixxSyncTableState:
        with Session(self.mirror.engine, expire_on_commit=False) as s:
            return get_or_create_table_state(s, self.company_id, OBJECT.name)

    def staged(self) -> int:
        with Session(self.mirror.engine) as s:
            return int(s.scalar(sa.select(sa.func.count()).select_from(BrixxReconcileSeen)) or 0)


@pytest.fixture
def env(dbos_runtime: None, migrated_engine: Engine, committed_company: Company) -> Iterator[Env]:
    from app.workflows.deps import set_engine

    with mirror_schema(migrated_engine) as mirror:
        set_engine(mirror.engine)
        yield Env(mirror, committed_company.id)
    set_brixx_api(None)


def test_reconcile_soft_deletes_rows_brixx_no_longer_has(env: Env) -> None:
    env.seed_mirror([obj(i, f"O-{i}") for i in (1, 2, 3, 4, 5)] + [obj(4, "O-4", version=2, indverwijderd=1)])
    env.seed_mirror([obj(8, "O-8")], synced_at=datetime.now(UTC) + timedelta(days=1))  # landed mid-reconcile
    env.brixx_has([obj(i, f"O-{i}") for i in (5, 1, 2, 4)])

    brixx_reconcile.reconcile_all(TICK, None)

    [run] = env.runs()
    assert (run.kind, run.status, run.error) == (BrixxRunKind.reconcile, BrixxRunStatus.succeeded, None)
    rows = env.mirror_rows()
    assert rows[3]._deleted_at is not None  # hard-deleted in BRIXX: soft-deleted here, row kept
    assert [pk for pk, row in sorted(rows.items()) if row._deleted_at is None] == [1, 2, 4, 5, 8]
    assert rows[4].indverwijderd == 1  # BRIXX's own soft delete is left as it is
    assert env.state().last_success_upd == WATERMARK  # nothing missing: no backfill needed
    assert env.staged() == 0
    assert set(env.api.order_log) == {"prg_objectid"}
    assert [filters for _t, _p, filters in env.api.fetch_log] == [None, "[prg_objectid > 2]"]


def test_reconcile_restores_relisted_rows_and_resets_watermark_for_missing_ones(env: Env) -> None:
    env.seed_mirror([obj(1, "O-1"), obj(2, "O-2")])
    with env.mirror.session() as s:
        s.execute(sa.update(env.table).where(env.table.c.prg_objectid == 2).values(_deleted_at=SYNCED))
        s.commit()
    env.brixx_has([obj(1, "O-1"), obj(2, "O-2"), obj(6, "O-6")], page_size=10)

    brixx_reconcile.reconcile_all(TICK, None)

    rows = env.mirror_rows()
    assert rows[2]._deleted_at is None
    assert 6 not in rows  # the reconcile never writes rows itself
    assert env.state().last_success_upd is None  # the next incremental run does a full fetch (backfill)


def test_same_day_tick_is_one_run_and_failed_table_is_reported(env: Env) -> None:
    env.seed_mirror([obj(1, "O-1"), obj(2, "O-2")])
    env.brixx_has([obj(1, "O-1")])
    brixx_reconcile.reconcile_all(TICK, None)
    brixx_reconcile.reconcile_all(TICK + timedelta(minutes=5), None)
    assert len(env.runs()) == 1

    from app.core.errors import BrixxAuthError

    env.brixx_has([obj(1, "O-1")])
    env.api.fail_on(OBJECT.name, 1, BrixxAuthError("rejected"), once=False)
    brixx_reconcile.reconcile_all(TICK + timedelta(days=1), None)
    failed = [r for r in env.runs() if r.status == BrixxRunStatus.failed]
    assert len(failed) == 1
    assert failed[0].error is not None
    assert "BrixxAuthError" in failed[0].error
    assert env.mirror_rows()[1]._deleted_at is None  # a failed scan never soft-deletes anything

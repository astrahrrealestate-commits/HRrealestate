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


def test_a_row_with_no_usable_primary_key_is_skipped_not_fatal(env: Env) -> None:
    """Seen for some real historical `Z*` rows: BRIXX itself sends no usable key value for a row. Permanent for
    that row, so it is dropped from the keyset rather than aborting the whole scan page (and retrying 8 times
    for nothing) -- the rest of the page still reconciles normally."""
    env.seed_mirror([obj(i, f"O-{i}") for i in (1, 2, 3)])
    env.brixx_has([obj(1, "O-1"), obj(2, "O-2", prg_objectid=None), obj(3, "O-3")], page_size=10)

    brixx_reconcile.reconcile_all(TICK, None)

    [run] = env.runs()
    assert (run.kind, run.status, run.error) == (BrixxRunKind.reconcile, BrixxRunStatus.succeeded, None)
    rows = env.mirror_rows()
    assert rows[1]._deleted_at is None
    assert rows[3]._deleted_at is None
    assert rows[2]._deleted_at is not None  # staged only under key 2 (seeded); the key-less row never staged


def test_a_page_mixing_good_and_bad_keys_still_advances_the_cursor(env: Env) -> None:
    """The shape that actually matters in production: a page with `has_next=True` whose rows are a MIX of good
    and bad keys, not just a single bad row on the final (has_next=False) page. A key-less row always sorts
    last in a keyset scan (NULLs sort last, both here and in real Postgres-backed BRIXX), so this needs more
    bad rows than fit in one page: two good keys plus five key-less rows, page_size=3, puts one key-less row on
    the first page alongside both good ones. The scan must skip it, advance the cursor using only the valid
    keys (not get stuck re-fetching page 1 forever), and the next page -- all remaining key-less rows -- must
    end the scan cleanly with no exception."""
    env.seed_mirror([obj(1, "O-1"), obj(2, "O-2")])
    env.brixx_has([obj(1, "O-1"), obj(2, "O-2"), *(obj(0, "no-key", prg_objectid=None) for _ in range(5))], page_size=3)

    brixx_reconcile.reconcile_all(TICK, None)

    [run] = env.runs()
    assert (run.kind, run.status, run.error) == (BrixxRunKind.reconcile, BrixxRunStatus.succeeded, None)
    rows = env.mirror_rows()
    assert rows[1]._deleted_at is None
    assert rows[2]._deleted_at is None


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

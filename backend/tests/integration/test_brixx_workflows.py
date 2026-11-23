"""BRIXX sync workflows end to end: real DBOS executor and Postgres, FakeBrixxApi, throwaway mirror schema."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError, BrixxNotFoundError
from app.db.enums import BrixxRunKind, BrixxRunStatus
from app.db.models import Company
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState
from app.directory.brixx.state import get_or_create_table_state
from app.directory.brixx.state import mark_success as real_mark_success
from app.workflows import brixx_sync
from app.workflows.deps import set_brixx_api
from tests.integration.brixx_support import MirrorSchema, mirror_schema

pytestmark = pytest.mark.integration

SCHEDULED = datetime(2026, 11, 1, 8, 15, tzinfo=UTC)
SECRET = "token-abc-123"


def _info(name: str) -> BrixxTable:
    return BrixxTable(
        name,
        "ID",
        (
            BrixxField(1, "ID", "NUMBER", True, None, None),
            BrixxField(2, "NAAM", "VARCHAR(50)", False, None, None),
            BrixxField(3, "VERSIENR", "NUMBER", False, None, None),
            BrixxField(4, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
        ),
    )


def _rows(count: int) -> list[dict[str, object]]:
    return [
        {"ID": i, "NAAM": f"n{i}", "VERSIENR": 1, "UPDDATETIME": f"2026-10-{20 + i:02d}T09:00:00"}
        for i in range(1, count + 1)
    ]


class Env:
    def __init__(self, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
        self.mirror = mirror
        self.company_id = company_id
        self.tables: dict[str, sa.Table] = {}
        self.api = FakeBrixxApi({})
        self.marked: list[str] = []

    def install(self, counts: dict[str, int], page_size: int = 2) -> FakeBrixxApi:
        fake_tables = {}
        for name, count in counts.items():
            info = _info(name)
            self.tables[name] = self.mirror.create(info)
            fake_tables[name] = FakeTable(info, _rows(count))
        self.api = FakeBrixxApi(fake_tables, page_size=page_size)
        set_brixx_api(self.api)
        return self.api

    def runs(self) -> list[BrixxSyncRun]:
        """Only the runs the test's own ticks created: the worker's real 15-minute cron can fire mid-suite and
        add a wall-clock run for the same company, which must not count."""
        expected = [brixx_sync.brixx_run_id(self.company_id, t) for t in (SCHEDULED, SCHEDULED.replace(minute=30))]
        with Session(self.mirror.engine) as s:
            return list(
                s.scalars(
                    sa.select(BrixxSyncRun).where(
                        BrixxSyncRun.company_id == self.company_id, BrixxSyncRun.id.in_(expected)
                    )
                )
            )

    def states(self) -> dict[str, BrixxSyncTableState]:
        with Session(self.mirror.engine, expire_on_commit=False) as s:
            found = s.scalars(sa.select(BrixxSyncTableState).where(BrixxSyncTableState.company_id == self.company_id))
            return {st.table_name: st for st in found}

    def mirrored(self, name: str) -> int:
        with Session(self.mirror.engine) as s:
            table = self.tables[name]
            query = sa.select(sa.func.count()).select_from(table).where(table.c.company_id == self.company_id)
            return int(s.scalar(query) or 0)

    def fetches(self, table: str) -> list[int]:
        return [page for name, page, _f in self.api.fetch_log if name == table]


@pytest.fixture
def env(
    dbos_runtime: None, migrated_engine: Engine, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Env]:
    from app.workflows.deps import set_engine

    with mirror_schema(migrated_engine) as mirror:
        set_engine(mirror.engine)  # steps see the throwaway schema behind the `brixx` name
        current = Env(mirror, committed_company.id)
        original = real_mark_success

        def counting(
            session: Session, state: BrixxSyncTableState, upd: datetime | None, started_at: datetime, run_id: uuid.UUID
        ) -> None:
            current.marked.append(state.table_name)
            original(session, state, upd, started_at, run_id)

        monkeypatch.setattr(brixx_sync, "mark_success", counting)
        yield current
    set_brixx_api(None)


def test_sync_all_creates_run_and_children(env: Env) -> None:
    env.install({"PRG_A": 5, "PRG_B": 2, "PRG_C": 0})
    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert (run.status, run.kind, run.error) == (BrixxRunStatus.succeeded, BrixxRunKind.incremental, None)
    assert run.finished_at is not None
    states = env.states()
    assert set(states) == {"PRG_A", "PRG_B", "PRG_C"}
    for name, count in {"PRG_A": 5, "PRG_B": 2, "PRG_C": 0}.items():
        state = states[name]
        assert (state.last_error, state.last_page, state.last_run_id) == (None, 0, run.id)
        assert env.mirrored(name) == count
    assert states["PRG_A"].row_count == 5
    assert states["PRG_A"].last_success_upd == datetime(2026, 10, 25, 8, 0, tzinfo=UTC)  # 09:00 CET (DST ended)
    assert sorted(env.marked) == ["PRG_A", "PRG_B", "PRG_C"]  # once each, after the last page
    assert env.fetches("PRG_A") == [1, 2, 3]


def test_repeat_enqueue_same_run_does_not_duplicate(env: Env) -> None:
    env.install({"PRG_A": 3, "PRG_B": 1})
    brixx_sync.sync_all(SCHEDULED, None)
    before = (env.runs()[0].id, set(env.states()), len(env.api.fetch_log))

    brixx_sync.sync_all(SCHEDULED, None)  # same cron tick delivered again

    assert [r.id for r in env.runs()] == [before[0]]
    assert set(env.states()) == before[1]
    assert len(env.api.fetch_log) == before[2]  # the children are already done: nothing is fetched again
    assert env.mirrored("PRG_A") == 3
    assert env.runs()[0].status == BrixxRunStatus.succeeded


def test_next_tick_is_a_new_run_that_refetches(env: Env) -> None:
    env.install({"PRG_A": 3})
    brixx_sync.sync_all(SCHEDULED, None)
    brixx_sync.sync_all(SCHEDULED.replace(minute=30), None)

    assert len(env.runs()) == 2
    assert len(env.states()) == 1
    assert env.mirrored("PRG_A") == 3
    assert sorted(env.marked) == ["PRG_A", "PRG_A"]


def test_one_table_auth_error_does_not_fail_others(env: Env) -> None:
    api = env.install({"PRG_A": 5, "PRG_B": 5, "PRG_C": 1})
    api.fail_on("PRG_B", 2, BrixxAuthError(SECRET), once=False)

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert run.status == BrixxRunStatus.failed
    assert run.finished_at is not None
    assert run.error is not None
    assert "BrixxAuthError" in run.error
    assert "PRG_B" in run.error
    assert "PRG_A" not in run.error
    assert SECRET not in run.error
    states = env.states()
    failed = states["PRG_B"]
    assert failed.last_error is not None
    assert failed.last_error.startswith("BrixxAuthError")
    assert SECRET not in failed.last_error
    assert (failed.last_page, failed.last_success_upd) == (1, None)  # resume point kept, watermark untouched
    for name in ("PRG_A", "PRG_C"):
        assert states[name].last_error is None
        assert states[name].last_success_upd is not None
    assert env.mirrored("PRG_A") == 5
    assert env.fetches("PRG_B") == [1, 2]  # page 2 fetched once: no retry storm
    assert "PRG_B" not in env.marked  # never marked successful on failure
    assert sorted(env.marked) == ["PRG_A", "PRG_C"]


def test_transient_error_on_page_two_resumes_and_marks_success_once(env: Env) -> None:
    api = env.install({"PRG_A": 5})
    api.fail_on("PRG_A", 2, BrixxError("upstream 503"), once=True)

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert run.status == BrixxRunStatus.succeeded
    assert env.mirrored("PRG_A") == 5
    assert env.fetches("PRG_A") == [1, 2, 2, 3]  # page 2 retried by DBOS, page 1 not refetched
    assert env.marked == ["PRG_A"]
    state = env.states()["PRG_A"]
    assert (state.last_error, state.last_page, state.row_count) == (None, 0, 5)


def test_list_tables_auth_error_fails_the_run_cleanly(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    api = env.install({"PRG_A": 1})
    calls: list[int] = []

    def refuse() -> list[tuple[str, str]]:
        calls.append(1)
        raise BrixxAuthError(SECRET)

    monkeypatch.setattr(api, "list_tables", refuse)

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert run.status == BrixxRunStatus.failed
    assert run.error is not None
    assert "BrixxAuthError" in run.error
    assert SECRET not in run.error
    assert calls == [1]  # not retried
    assert env.states() == {}


def test_restart_after_the_last_page_copes_with_an_empty_next_page(env: Env, migrated_engine: Engine) -> None:
    env.install({"PRG_A": 6})  # 3 pages of 2: page 3 is the last
    run_id = uuid.uuid4()
    with Session(env.mirror.engine) as s:  # a same-run restart: pages 1-3 are committed, mark_success never ran
        s.add(BrixxSyncRun(id=run_id, company_id=env.company_id, kind=BrixxRunKind.incremental, started_at=SCHEDULED))
        s.commit()
        state = get_or_create_table_state(s, env.company_id, "PRG_A")
        state.last_run_id, state.last_page, state.row_count = run_id, 3, 6
        s.commit()

    assert brixx_sync.sync_table(str(run_id), "PRG_A") == brixx_sync.OK

    assert env.fetches("PRG_A") == [4]  # the page after the last one comes back empty with has_next False
    state = env.states()["PRG_A"]
    assert (state.last_page, state.last_error) == (0, None)
    assert env.marked == ["PRG_A"]


def test_stale_run_is_not_retried_and_fails_that_table_only(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    api = env.install({"PRG_A": 5, "PRG_B": 1})
    rival = uuid.uuid4()
    with Session(env.mirror.engine) as s:
        s.add(BrixxSyncRun(id=rival, company_id=env.company_id, kind=BrixxRunKind.reconcile, started_at=SCHEDULED))
        s.commit()
    real_fetch = api.fetch_page

    def takeover(table: str, **kwargs: object) -> object:
        if table == "PRG_A" and kwargs["page"] == 2:  # another run takes PRG_A over while this one is mid-table
            with Session(env.mirror.engine) as s:
                state = get_or_create_table_state(s, env.company_id, "PRG_A")
                state.last_run_id, state.last_page = rival, 0
                s.commit()
        return real_fetch(table, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api, "fetch_page", takeover)

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = [r for r in env.runs() if r.kind == BrixxRunKind.incremental]
    assert run.status == BrixxRunStatus.failed
    assert run.error is not None
    assert "StaleRunError" in run.error
    assert env.fetches("PRG_A") == [1, 2]  # StaleRunError is not retried
    assert env.marked == ["PRG_B"]


def test_empty_fake_is_a_quiet_no_op(env: Env) -> None:
    set_brixx_api(FakeBrixxApi({}))

    brixx_sync.sync_all(SCHEDULED, None)

    assert env.runs() == []
    assert env.states() == {}


def test_table_without_a_mirror_table_is_skipped_as_drift_not_failure(env: Env) -> None:
    env.install({"PRG_A": 3})
    unmigrated = _info("PRG_NEW")  # BRIXX lists it, but no codegen revision has created its mirror table yet
    tables = {"PRG_A": FakeTable(_info("PRG_A"), _rows(3)), "PRG_NEW": FakeTable(unmigrated, _rows(2))}
    api = FakeBrixxApi(tables, page_size=2)
    set_brixx_api(api)
    env.api = api

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert (run.status, run.error) == (BrixxRunStatus.succeeded, None)
    states = env.states()
    assert states["PRG_NEW"].drifted is True
    assert states["PRG_NEW"].last_run_id is None  # skipped before any takeover
    assert env.fetches("PRG_NEW") == []
    assert states["PRG_A"].drifted is False
    assert env.mirrored("PRG_A") == 3
    assert "PRG_NEW" not in env.marked


def test_live_column_the_mirror_lacks_lands_in_extra_and_flags_drift(env: Env) -> None:
    narrow = _info("PRG_A")
    env.tables["PRG_A"] = env.mirror.create(narrow)  # what the committed revision created
    grown = BrixxTable("PRG_A", "ID", (*narrow.fields, BrixxField(5, "NIEUW", "VARCHAR(5)", False, None, None)))
    rows = [{**row, "NIEUW": "x"} for row in _rows(2)]
    api = FakeBrixxApi({"PRG_A": FakeTable(grown, rows)}, page_size=2)
    set_brixx_api(api)
    env.api = api

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert run.status == BrixxRunStatus.succeeded
    assert env.states()["PRG_A"].drifted is True
    table = env.tables["PRG_A"]
    with Session(env.mirror.engine) as s:
        extras = list(s.scalars(sa.select(table.c._extra).where(table.c.company_id == env.company_id)))
    assert extras == [{"nieuw": "x"}, {"nieuw": "x"}]


def test_listed_table_brixx_cannot_describe_is_skipped_not_a_failed_run(env: Env) -> None:
    api = env.install({"PRG_A": 3, "PG_CLASS": 1})  # BRIXX lists Postgres catalogs it then answers 404 for
    api.fail_describe("PG_CLASS", BrixxNotFoundError("BRIXX request failed (HTTP 404)"), once=False)

    brixx_sync.sync_all(SCHEDULED, None)

    [run] = env.runs()
    assert (run.status, run.error) == (BrixxRunStatus.succeeded, None)  # else the dashboard shows "Stale" forever
    assert env.mirrored("PRG_A") == 3
    assert env.fetches("PG_CLASS") == []
    assert "PG_CLASS" not in env.marked

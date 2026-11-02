"""BRIXX table sync against a real Postgres and the strict FakeBrixxApi: filters, resume, drift, errors, tenants."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError
from app.db.enums import BrixxRunKind
from app.db.models import Company
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState
from app.directory.brixx.state import begin_table_run, get_or_create_table_state, mark_success, record_page
from app.directory.brixx.sync import PageResult, latest, sync_table_page
from tests.integration.brixx_support import (
    MirrorSchema,
    mirror_schema,
    plain_table_info,
    versioned_table_info,
)
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
LEAK_PROBE = "probe-value-must-not-be-stored"


@pytest.fixture
def mirror(migrated_engine: Engine) -> Iterator[MirrorSchema]:
    with mirror_schema(migrated_engine) as schema:
        yield schema


@pytest.fixture
def company_id(committed_company: Company) -> uuid.UUID:
    return committed_company.id


@pytest.fixture
def session(mirror: MirrorSchema, company_id: uuid.UUID) -> Iterator[Session]:
    """Requests the company first so the session closes (releasing its row locks) before the company is purged."""
    with mirror.session() as s:
        yield s


@pytest.fixture
def other_company_id(migrated_engine: Engine) -> Iterator[uuid.UUID]:
    with Session(migrated_engine) as s:
        other = Company(name="Other GmbH")
        s.add(other)
        s.commit()
        other_id = other.id
    yield other_id
    purge_company(migrated_engine, other_id)


def _rows(count: int) -> list[dict[str, object]]:
    return [
        {"ID": i, "NAAM": f"n{i}", "VERSIENR": 1, "UPDDATETIME": f"2026-10-{20 + i:02d} 09:00:00"}
        for i in range(1, count + 1)
    ]


def _api(info: BrixxTable, rows: list[dict[str, object]], page_size: int = 2) -> FakeBrixxApi:
    return FakeBrixxApi({info.name: FakeTable(info, rows)}, page_size=page_size)


def _run(
    session: Session,
    api: FakeBrixxApi,
    company: uuid.UUID,
    info: BrixxTable,
    table: sa.Table,
    run_id: uuid.UUID,
    *,
    since: datetime | None = None,
) -> datetime | None:
    """What the Task 8 workflow does: start page from state, loop pages, mark success only after the last."""
    state = get_or_create_table_state(session, company, info.name)
    page = begin_table_run(session, state, run_id)
    session.commit()
    max_upd: datetime | None = None
    while True:
        result: PageResult = sync_table_page(session, api, company, info, table, page=page, since=since, now=NOW)
        max_upd = latest(max_upd, result.max_upd)
        if not result.has_next:
            break
        page += 1
    state = get_or_create_table_state(session, company, info.name)
    mark_success(session, state, max_upd, NOW)
    session.commit()
    return max_upd


def _new_run(session: Session, company: uuid.UUID) -> uuid.UUID:
    """Table state links to a real run row (FK), so every test run needs one."""
    run = BrixxSyncRun(company_id=company, kind=BrixxRunKind.incremental, started_at=NOW)
    session.add(run)
    session.commit()
    return run.id


def _state(session: Session, company: uuid.UUID, table: str) -> BrixxSyncTableState:
    session.expire_all()
    return get_or_create_table_state(session, company, table)


def _ids(session: Session, table: sa.Table, company: uuid.UUID) -> list[int]:
    found = session.execute(sa.select(table.c.id).where(table.c.company_id == company).order_by(table.c.id))
    return [r.id for r in found]


def test_first_run_is_full_load(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, _rows(5))
    _run(session, api, company_id, info, table, _new_run(session, company_id))
    assert api.fetch_log == [("PRG_DEMO", 1, None), ("PRG_DEMO", 2, None), ("PRG_DEMO", 3, None)]
    assert _ids(session, table, company_id) == [1, 2, 3, 4, 5]
    state = _state(session, company_id, info.name)
    assert state.row_count == 5
    assert state.last_page == 0
    assert state.last_error is None


def test_max_upd_parses_naive_amsterdam_strings(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    rows = _rows(3)
    rows[1]["UPDDATETIME"] = "2026-10-31 23:30:00"  # CET (UTC+1) after the DST switch -> 22:30 UTC
    api = _api(info, rows)
    max_upd = _run(session, api, company_id, info, table, _new_run(session, company_id))
    assert max_upd == datetime(2026, 10, 31, 22, 30, tzinfo=UTC)
    assert _state(session, company_id, info.name).last_success_upd == datetime(2026, 10, 31, 22, 30, tzinfo=UTC)


def test_incremental_sends_filter_with_overlap(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, _rows(5))
    since = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    _run(session, api, company_id, info, table, _new_run(session, company_id), since=since)
    assert {entry[2] for entry in api.fetch_log} == {"[upddatetime >= 2026-10-23]"}  # since minus 5 min minus 1 day
    assert _ids(session, table, company_id) == [3, 4, 5]  # rows dated 10-23 onwards; 1 and 2 are older


def test_no_upddatetime_table_full_fetch(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = plain_table_info()
    table = mirror.create(info)
    api = _api(info, [{"ID": i, "NAAM": f"n{i}"} for i in range(1, 4)])
    since = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    _run(session, api, company_id, info, table, _new_run(session, company_id), since=since)
    _run(session, api, company_id, info, table, _new_run(session, company_id), since=since)  # rewriting rows is fine
    assert {entry[2] for entry in api.fetch_log} == {None}
    assert _ids(session, table, company_id) == [1, 2, 3]
    assert _state(session, company_id, info.name).last_success_upd is None


def test_resume_after_crash_does_not_refetch_earlier_pages(
    session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, _rows(7))  # 4 pages of 2
    api.fail_on(info.name, 3, BrixxError("transient"))
    run_id = _new_run(session, company_id)
    with pytest.raises(BrixxError):
        _run(session, api, company_id, info, table, run_id)
    state = _state(session, company_id, info.name)
    assert state.last_page == 2
    assert state.last_success_upd is None
    assert state.last_error == "BrixxError table=PRG_DEMO page=3"
    assert _ids(session, table, company_id) == [1, 2, 3, 4]

    api.fetch_log.clear()
    _run(session, api, company_id, info, table, run_id)
    assert [entry[1] for entry in api.fetch_log] == [3, 4]
    state = _state(session, company_id, info.name)
    assert state.last_success_upd is not None
    assert state.last_page == 0
    assert state.last_error is None
    assert state.row_count == 7
    assert _ids(session, table, company_id) == [1, 2, 3, 4, 5, 6, 7]


def test_new_run_starts_at_page_one_even_after_a_crash(
    session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, _rows(5))
    api.fail_on(info.name, 2, BrixxError("transient"))
    with pytest.raises(BrixxError):
        _run(session, api, company_id, info, table, _new_run(session, company_id))
    api.fetch_log.clear()
    _run(session, api, company_id, info, table, _new_run(session, company_id))
    assert [entry[1] for entry in api.fetch_log] == [1, 2, 3]


def test_success_only_after_last_page_and_never_on_failure(
    session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    watermark = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    state = get_or_create_table_state(session, company_id, info.name)
    state.last_success_upd = watermark
    session.commit()
    api = _api(info, _rows(5))
    api.fail_on(info.name, 3, BrixxError("transient"))
    with pytest.raises(BrixxError):
        _run(session, api, company_id, info, table, _new_run(session, company_id), since=watermark)
    assert _state(session, company_id, info.name).last_success_upd == watermark


def test_mark_success_is_monotonic_and_capped(session: Session, company_id: uuid.UUID) -> None:
    state = get_or_create_table_state(session, company_id, "PRG_DEMO")
    started = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
    mark_success(session, state, datetime(2026, 10, 30, tzinfo=UTC), started)
    mark_success(session, state, datetime(2026, 10, 1, tzinfo=UTC), started)
    assert state.last_success_upd == datetime(2026, 10, 30, tzinfo=UTC)
    mark_success(session, state, None, started)
    assert state.last_success_upd == datetime(2026, 10, 30, tzinfo=UTC)
    mark_success(session, state, started + timedelta(days=30), started)
    assert state.last_success_upd == started


def test_record_page_does_not_double_count_a_replayed_page(session: Session, company_id: uuid.UUID) -> None:
    state = get_or_create_table_state(session, company_id, "PRG_DEMO")
    record_page(session, state, 1, 2)
    record_page(session, state, 1, 2)
    record_page(session, state, 2, 1)
    assert (state.last_page, state.row_count) == (2, 3)


def test_drift_flagged_not_failed(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    mirrored = versioned_table_info()
    table = mirror.create(mirrored)
    grown = BrixxTable(
        mirrored.name,
        mirrored.primary_key,
        (*mirrored.fields, BrixxField(9, "NIEUW", "VARCHAR(5)", False, None, None)),
    )
    api = _api(grown, [{**r, "NIEUW": "x"} for r in _rows(3)])
    _run(session, api, company_id, grown, table, _new_run(session, company_id))
    state = _state(session, company_id, grown.name)
    assert state.drifted is True
    assert state.last_error is None
    assert state.last_success_upd is not None
    assert _ids(session, table, company_id) == [1, 2, 3]


def test_unknown_row_column_flags_drift_without_failing(
    session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, [{**r, "SURPRISE": 1} for r in _rows(2)])
    _run(session, api, company_id, info, table, _new_run(session, company_id))
    state = _state(session, company_id, info.name)
    assert state.drifted is True
    assert state.last_error is None


def test_no_drift_when_schema_matches(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    _run(session, _api(info, _rows(2)), company_id, info, table, _new_run(session, company_id))
    assert _state(session, company_id, info.name).drifted is False


def test_auth_error_recorded_with_class_name_only(
    session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    api = _api(info, _rows(3))
    api.fail_on(info.name, 1, BrixxAuthError(f"401 for https://x/api?ZOEKID={LEAK_PROBE}"))
    with pytest.raises(BrixxAuthError):
        _run(session, api, company_id, info, table, _new_run(session, company_id))
    state = _state(session, company_id, info.name)
    assert state.last_error == "BrixxAuthError table=PRG_DEMO page=1"
    assert LEAK_PROBE not in (state.last_error or "")
    assert state.last_success_upd is None


def test_failed_page_is_rolled_back_and_recorded(session: Session, mirror: MirrorSchema, company_id: uuid.UUID) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    rows = _rows(2)
    del rows[1]["ID"]
    api = _api(info, rows)
    with pytest.raises(BrixxError):
        _run(session, api, company_id, info, table, _new_run(session, company_id))
    assert _ids(session, table, company_id) == []
    state = _state(session, company_id, info.name)
    assert state.last_page == 0
    assert state.last_error == "BrixxError table=PRG_DEMO page=1"


def test_tenant_scoping_same_table_separate_state(
    other_company_id: uuid.UUID, session: Session, mirror: MirrorSchema, company_id: uuid.UUID
) -> None:
    info = versioned_table_info()
    table = mirror.create(info)
    _run(session, _api(info, _rows(5)), company_id, info, table, _new_run(session, company_id))
    other_api = _api(info, _rows(2))
    other_api.fail_on(info.name, 1, BrixxError("transient"))
    with pytest.raises(BrixxError):
        _run(session, other_api, other_company_id, info, table, _new_run(session, other_company_id))

    mine = _state(session, company_id, info.name)
    theirs = _state(session, other_company_id, info.name)
    assert mine.id != theirs.id
    assert (mine.row_count, mine.last_error) == (5, None)
    assert theirs.last_error == "BrixxError table=PRG_DEMO page=1"
    assert theirs.last_success_upd is None
    assert mine.last_success_upd is not None
    assert _ids(session, table, company_id) == [1, 2, 3, 4, 5]
    assert _ids(session, table, other_company_id) == []

"""The BRIXX page upsert: idempotent, never lets an older row win, tenant-scoped, keeps unknown columns."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.errors import BrixxError
from app.directory.brixx import upsert as upsert_module
from app.directory.brixx.upsert import UpsertResult, upsert_page
from tests.integration.brixx_support import (
    MirrorSchema,
    mirror_schema,
    plain_table_info,
    timestamp_only_table_info,
    versioned_table_info,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SYNCED = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)


@pytest.fixture
def mirror(migrated_engine: Engine) -> Iterator[MirrorSchema]:
    with mirror_schema(migrated_engine) as schema:
        yield schema


@pytest.fixture
def session(mirror: MirrorSchema) -> Iterator[Session]:
    with mirror.session() as s:
        yield s


@pytest.fixture
def table(mirror: MirrorSchema) -> sa.Table:
    return mirror.create(versioned_table_info())


def _row(
    pk: int | str, naam: str, version: int | None, upd: datetime | None = T0, **extra: object
) -> dict[str, object]:
    return {"ID": pk, "NAAM": naam, "VERSIENR": version, "UPDDATETIME": upd, **extra}


def _write(session: Session, table: sa.Table, company: uuid.UUID, rows: list[dict[str, object]]) -> UpsertResult:
    return upsert_page(session, table, versioned_table_info(), company, rows, SYNCED)


def _rows(session: Session, table: sa.Table, company: uuid.UUID) -> dict[int, Any]:
    found = session.execute(sa.select(table).where(table.c.company_id == company)).all()
    return {r.id: r for r in found}


def test_insert_then_update(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    first = _write(session, table, company, [_row(1, "Jansen", 1)])
    second = _write(session, table, company, [_row(1, "Jansen-Bakker", 2, T0 + timedelta(hours=1))])
    rows = _rows(session, table, company)
    assert (first.written, first.skipped_older) == (1, 0)
    assert (second.written, second.skipped_older) == (1, 0)
    assert len(rows) == 1
    assert rows[1].naam == "Jansen-Bakker"
    assert rows[1].versienr == Decimal(2)
    assert rows[1]._synced_at == SYNCED


def test_replay_same_page_is_noop_count(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    page = [_row(1, "A", 3), _row(2, "B", 3)]
    _write(session, table, company, page)
    before = {pk: (r.naam, r.versienr, r.upddatetime, r._extra) for pk, r in _rows(session, table, company).items()}
    replay = _write(session, table, company, page)
    after = {pk: (r.naam, r.versienr, r.upddatetime, r._extra) for pk, r in _rows(session, table, company).items()}
    assert (replay.written, replay.skipped_older) == (2, 0)
    assert after == before


def test_older_version_never_wins(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "new", 2)])
    result = _write(session, table, company, [_row(1, "old", 1)])
    assert (result.written, result.skipped_older) == (0, 1)
    row = _rows(session, table, company)[1]
    assert row.naam == "new"
    assert row.versienr == Decimal(2)


def test_equal_version_older_upddatetime_does_not_overwrite(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "newer", 5, T0)])
    stale = _write(session, table, company, [_row(1, "stale", 5, T0 - timedelta(minutes=1))])
    assert (stale.written, stale.skipped_older) == (0, 1)
    assert _rows(session, table, company)[1].naam == "newer"
    fresh = _write(session, table, company, [_row(1, "fresher", 5, T0 + timedelta(minutes=1))])
    assert (fresh.written, fresh.skipped_older) == (1, 0)
    assert _rows(session, table, company)[1].naam == "fresher"


def test_null_stored_version_is_overwritten(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "unversioned", None, None)])
    result = _write(session, table, company, [_row(1, "versioned", 1)])
    assert result.written == 1
    assert _rows(session, table, company)[1].naam == "versioned"


def test_unknown_column_goes_to_extra(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    result = _write(session, table, company, [_row(1, "A", 1, NIEUW="x", Ander=2)])
    assert result.extra_columns == frozenset({"nieuw", "ander"})
    assert _rows(session, table, company)[1]._extra == {"nieuw": "x", "ander": 2}


def test_null_object_stored_as_null(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [{"ID": 1, "NAAM": {}, "VERSIENR": {}, "UPDDATETIME": {}}])
    row = _rows(session, table, company)[1]
    assert row.naam is None
    assert row.versienr is None
    assert row.upddatetime is None


def test_no_extras_is_sql_null_not_json_null(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    result = _write(session, table, company, [_row(1, "A", 1), _row(2, "B", 1, WEG=None)])
    assert result.extra_columns == frozenset({"weg"})
    sql_null = session.scalars(sa.select(table.c.id).where(table.c._extra.is_(None), table.c.company_id == company))
    assert sorted(sql_null.all()) == [1]


def test_deleted_at_cleared_on_rewrite(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "A", 1)])
    session.execute(sa.update(table).where(table.c.company_id == company).values(_deleted_at=T0))
    assert _rows(session, table, company)[1]._deleted_at == T0
    _write(session, table, company, [_row(1, "A", 1)])
    assert _rows(session, table, company)[1]._deleted_at is None


def test_two_companies_isolated(session: Session, table: sa.Table) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    _write(session, table, a, [_row(1, "from-a", 1)])
    _write(session, table, b, [_row(1, "from-b", 9)])
    assert _rows(session, table, a)[1].naam == "from-a"
    assert _rows(session, table, b)[1].naam == "from-b"
    stale_for_a = _write(session, table, a, [_row(1, "a-again", 1)])
    newer_for_a = _write(session, table, a, [_row(1, "a-newer", 2)])
    assert (stale_for_a.written, newer_for_a.written) == (1, 1)
    assert _rows(session, table, a)[1].naam == "a-newer"
    assert _rows(session, table, b)[1].naam == "from-b"
    assert _rows(session, table, b)[1].versienr == Decimal(9)
    assert session.scalar(sa.select(sa.func.count()).select_from(table)) == 2


def test_page_larger_than_one_statement(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    count = 12_000
    result = _write(session, table, company, [_row(i, f"n{i}", 1) for i in range(count)])
    assert (result.written, result.skipped_older) == (count, 0)
    assert session.scalar(sa.select(sa.func.count()).select_from(table)) == count


def test_small_chunks_split_page(session: Session, table: sa.Table, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upsert_module, "MAX_BIND_PARAMS", 60)
    company = uuid.uuid4()
    result = _write(session, table, company, [_row(i, f"n{i}", 1) for i in range(25)])
    assert result.written == 25
    assert len(_rows(session, table, company)) == 25


def test_duplicate_key_in_page_keeps_highest_version(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    result = _write(session, table, company, [_row(1, "v2", 2), _row(1, "v3", 3), _row(1, "v1", 1)])
    assert (result.written, result.skipped_older) == (1, 2)
    assert _rows(session, table, company)[1].naam == "v3"


def test_table_without_version_columns_always_overwrites(mirror: MirrorSchema, session: Session) -> None:
    plain = mirror.create(plain_table_info())
    company = uuid.uuid4()
    info = plain_table_info()
    upsert_page(session, plain, info, company, [{"ID": 1, "NAAM": "first"}], SYNCED)
    result = upsert_page(session, plain, info, company, [{"ID": 1, "NAAM": "second"}], SYNCED)
    assert (result.written, result.skipped_older) == (1, 0)
    assert _rows(session, plain, company)[1].naam == "second"


def test_keys_match_columns_case_insensitively(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    upper = {"ID": 1, "NAAM": "UP", "VERSIENR": 1, "UPDDATETIME": T0}
    lower = {"id": 2, "naam": "low", "versienr": 1, "upddatetime": T0}
    result = _write(session, table, company, [upper, lower])
    rows = _rows(session, table, company)
    assert result.extra_columns == frozenset()
    assert (rows[1].naam, rows[2].naam) == ("UP", "low")


def test_row_without_primary_key_is_skipped_not_raised(session: Session, table: sa.Table) -> None:
    """Seen for some real historical `Z*` rows: BRIXX itself sends no usable key. Permanent for that row, so it
    is dropped rather than aborting the whole page (and retrying 8 times for nothing)."""
    result = _write(session, table, uuid.uuid4(), [{"NAAM": "no key", "VERSIENR": 1}])
    assert result.written == 0


def test_one_bad_row_does_not_abort_the_rest_of_the_page(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    result = _write(session, table, company, [{"NAAM": "no key", "VERSIENR": 1}, _row(1, "good", 1)])
    rows = _rows(session, table, company)
    assert result.written == 1
    assert rows[1].naam == "good"


def test_empty_page_is_noop(session: Session, table: sa.Table) -> None:
    result = _write(session, table, uuid.uuid4(), [])
    assert result == UpsertResult(0, 0, frozenset())


def test_incoming_null_version_never_beats_stored_version(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "v5", 5)])
    result = _write(session, table, company, [_row(1, "unversioned", None)])
    assert (result.written, result.skipped_older) == (0, 1)
    assert _rows(session, table, company)[1].naam == "v5"


def test_both_versions_null_falls_back_to_upddatetime(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "newer", None, T0)])
    stale = _write(session, table, company, [_row(1, "stale", None, T0 - timedelta(minutes=1))])
    assert (stale.written, stale.skipped_older) == (0, 1)
    fresh = _write(session, table, company, [_row(1, "fresh", None, T0 + timedelta(minutes=1))])
    assert (fresh.written, fresh.skipped_older) == (1, 0)
    assert _rows(session, table, company)[1].naam == "fresh"


def test_equal_version_incoming_null_upddatetime_is_skipped(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "stamped", 5, T0)])
    result = _write(session, table, company, [_row(1, "unstamped", 5, None)])
    assert (result.written, result.skipped_older) == (0, 1)
    assert _rows(session, table, company)[1].naam == "stamped"


def test_everything_null_overwrites(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "first", None, None)])
    result = _write(session, table, company, [_row(1, "second", None, None)])
    assert (result.written, result.skipped_older) == (1, 0)
    assert _rows(session, table, company)[1].naam == "second"


def test_timestamp_only_table_orders_by_upddatetime(mirror: MirrorSchema, session: Session) -> None:
    stamp = mirror.create(timestamp_only_table_info())
    info = timestamp_only_table_info()
    company = uuid.uuid4()
    upsert_page(session, stamp, info, company, [{"ID": 1, "NAAM": "now", "UPDDATETIME": T0}], SYNCED)
    old = [{"ID": 1, "NAAM": "old", "UPDDATETIME": T0 - timedelta(hours=1)}]
    stale = upsert_page(session, stamp, info, company, old, SYNCED)
    new = [{"ID": 1, "NAAM": "newer", "UPDDATETIME": T0 + timedelta(hours=1)}]
    fresh = upsert_page(session, stamp, info, company, new, SYNCED)
    assert (stale.written, stale.skipped_older) == (0, 1)
    assert (fresh.written, fresh.skipped_older) == (1, 0)
    assert _rows(session, stamp, company)[1].naam == "newer"


def test_mixed_page_skips_and_writes_per_row(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    _write(session, table, company, [_row(1, "one-v2", 2), _row(2, "two-v1", 1)])
    result = _write(session, table, company, [_row(1, "one-v1", 1), _row(2, "two-v2", 2)])
    rows = _rows(session, table, company)
    assert (result.written, result.skipped_older) == (1, 1)
    assert (rows[1].naam, rows[1].versienr) == ("one-v2", Decimal(2))
    assert (rows[2].naam, rows[2].versienr) == ("two-v2", Decimal(2))


def test_primary_key_int_and_string_collapse_in_page(session: Session, table: sa.Table) -> None:
    company = uuid.uuid4()
    result = _write(session, table, company, [_row(1, "int", 1), _row("1", "str", 2)])
    assert (result.written, result.skipped_older) == (1, 1)
    assert _rows(session, table, company)[1].naam == "str"


def test_non_integer_primary_key_is_skipped_without_echoing_it(
    session: Session, table: sa.Table, capsys: pytest.CaptureFixture[str]
) -> None:
    result = _write(session, table, uuid.uuid4(), [{"ID": "SECRET-ZOEKID", "NAAM": "x", "VERSIENR": 1}])
    assert result.written == 0
    out = capsys.readouterr().out
    assert "SECRET-ZOEKID" not in out
    assert "PRG_DEMO" in out


def test_naive_synced_at_is_rejected(session: Session, table: sa.Table) -> None:
    with pytest.raises(BrixxError):
        upsert_page(
            session,
            table,
            versioned_table_info(),
            uuid.uuid4(),
            [_row(1, "A", 1)],
            datetime.fromisoformat("2026-11-01T08:00:00"),
        )

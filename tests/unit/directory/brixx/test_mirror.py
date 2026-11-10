"""What the sync may write: live BRIXX metadata narrowed to the columns the migrated mirror table really has."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.channels.brixx.models import BrixxField, BrixxTable
from app.directory.brixx.mirror import storable
from app.directory.brixx.schema import build_table

DIALECT = postgresql.dialect()


def _info(*extra: BrixxField) -> BrixxTable:
    return BrixxTable(
        "PRG_DEMO",
        "ID",
        (
            BrixxField(1, "ID", "NUMBER", True, None, None),
            BrixxField(2, "NAAM", "VARCHAR(50)", False, None, None),
            BrixxField(3, "UPDDATETIME", "TIMESTAMP(6)", False, None, None),
            *extra,
        ),
    )


def _reflected(info: BrixxTable) -> dict[str, str]:
    """What `mirror_columns` returns for a table the generated migration created from `info`."""
    reflected = {
        "company_id": postgresql.UUID(),
        "id": sa.BIGINT(),
        "naam": sa.VARCHAR(length=50),
        "upddatetime": postgresql.TIMESTAMP(timezone=True),
        "_synced_at": postgresql.TIMESTAMP(timezone=True),
        "_deleted_at": postgresql.TIMESTAMP(timezone=True),
        "_extra": postgresql.JSONB(),
    }
    assert set(reflected) == {c.name for c in build_table(info, sa.MetaData()).c}
    return {name: kind.compile(dialect=DIALECT) for name, kind in reflected.items()}


def test_reflected_types_compile_like_the_built_ones() -> None:
    built = build_table(_info(), sa.MetaData())
    reflected = _reflected(_info())
    for column in built.c:
        if not column.name.startswith("_") and column.name != "company_id":
            assert column.type.compile(dialect=DIALECT) == reflected[column.name], column.name


def test_matching_mirror_stores_every_field() -> None:
    assert storable(_info(), _reflected(_info()), DIALECT) == _info()


def test_new_live_column_is_left_out_so_it_lands_in_extra() -> None:
    grown = _info(BrixxField(4, "NIEUW", "VARCHAR(10)", False, None, None))
    assert storable(grown, _reflected(_info()), DIALECT) == _info()


def test_changed_type_is_left_out() -> None:
    naam = BrixxField(2, "NAAM", "VARCHAR(90)", False, None, None)
    widened = BrixxTable("PRG_DEMO", "ID", (*_info().fields[:1], naam))
    stored = storable(widened, _reflected(_info()), DIALECT)
    assert stored is not None
    assert [f.name for f in stored.fields] == ["ID"]


def test_missing_table_or_primary_key_or_system_columns_is_not_storable() -> None:
    mirror = _reflected(_info())
    assert storable(_info(), None, DIALECT) is None
    assert storable(_info(), {k: v for k, v in mirror.items() if k != "id"}, DIALECT) is None
    assert storable(_info(), {k: v for k, v in mirror.items() if k != "_extra"}, DIALECT) is None

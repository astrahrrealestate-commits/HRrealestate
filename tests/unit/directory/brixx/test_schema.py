import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.channels.brixx.models import BrixxField, BrixxTable
from app.core.errors import BrixxError
from app.db.base import Base
from app.directory.brixx.schema import (
    MIRROR_SCHEMA,
    build_table,
    has_incremental_column,
    sql_type,
)


def _field(name: str, type_: str = "VARCHAR(10)", fk_table: str | None = None) -> BrixxField:
    return BrixxField(1, name, type_, False, fk_table, "X" if fk_table else None)


def _info(*fields: BrixxField, name: str = "PRG_RELATIE", pk: str = "PRG_RELATIEID") -> BrixxTable:
    return BrixxTable(name, pk, (_field(pk, "NUMBER"), *fields))


@pytest.mark.parametrize(
    ("brixx_type", "is_key", "expected"),
    [
        ("NUMBER", True, sa.BigInteger),
        ("NUMBER", False, sa.Numeric),
        ("number", False, sa.Numeric),
        ("NUMBER(10,2)", False, sa.Numeric),
        ("VARCHAR(132)", False, sa.String),
        ("VARCHAR2(20)", False, sa.String),
        ("DATE", False, sa.Date),
        ("TIMESTAMP", False, sa.DateTime),
        ("TIMESTAMP(6)", False, sa.DateTime),
        ("DATETIME", False, sa.DateTime),
        ("BLOB", False, sa.Text),
    ],
)
def test_type_map(brixx_type: str, is_key: bool, expected: type) -> None:
    assert type(sql_type(brixx_type, is_key=is_key)) is expected


def test_type_map_details() -> None:
    varchar = sql_type("VARCHAR(132)", is_key=False)
    assert isinstance(varchar, sa.String)
    assert varchar.length == 132
    number = sql_type("NUMBER", is_key=False)
    assert isinstance(number, sa.Numeric)
    assert number.precision is None
    assert number.scale is None
    ts = sql_type("TIMESTAMP(6)", is_key=False)
    assert isinstance(ts, sa.DateTime)
    assert ts.timezone is True


def test_build_table_columns() -> None:
    info = _info(_field("NAAM"), _field("Mixed_Case", "DATE"))
    table = build_table(info, sa.MetaData())
    assert table.schema == MIRROR_SCHEMA == "brixx"
    assert table.name == "prg_relatie"
    assert {"prg_relatieid", "naam", "mixed_case"} <= set(table.c.keys())
    assert {"company_id", "_synced_at", "_deleted_at", "_extra"} <= set(table.c.keys())
    assert [c.name for c in table.primary_key.columns] == ["company_id", "prg_relatieid"]


def test_system_column_types() -> None:
    table = build_table(_info(), sa.MetaData())
    assert isinstance(table.c.company_id.type, sa.Uuid)
    assert table.c.company_id.nullable is False
    assert not table.c.company_id.foreign_keys
    assert isinstance(table.c._synced_at.type, sa.DateTime)
    assert table.c._synced_at.type.timezone is True
    assert table.c._synced_at.nullable is False
    assert table.c._deleted_at.nullable is True
    assert isinstance(table.c._extra.type, postgresql.JSONB)


def test_key_columns_are_bigint() -> None:
    info = _info(_field("RELATIEID", "NUMBER"), _field("AANTAL", "NUMBER"), _field("LINK", "NUMBER", fk_table="X"))
    table = build_table(info, sa.MetaData())
    assert isinstance(table.c.prg_relatieid.type, sa.BigInteger)
    assert isinstance(table.c.relatieid.type, sa.BigInteger)
    assert isinstance(table.c.link.type, sa.BigInteger)
    assert type(table.c.aantal.type) is sa.Numeric


def test_fk_column_indexed() -> None:
    info = _info(_field("OBJECTID", "NUMBER", fk_table="PRG_OBJECT"), _field("NAAM"))
    table = build_table(info, sa.MetaData())
    indexed = {tuple(c.name for c in ix.columns) for ix in table.indexes}
    assert ("objectid",) in indexed
    assert ("naam",) not in indexed


def test_upddatetime_indexed() -> None:
    table = build_table(_info(_field("UPDDATETIME", "TIMESTAMP")), sa.MetaData())
    assert {tuple(c.name for c in ix.columns) for ix in table.indexes} == {("upddatetime",)}


def test_index_names_explicit_and_short() -> None:
    info = _info(_field("A" * 40, "NUMBER", fk_table="T"), name="B" * 40, pk="PK")
    table = build_table(info, sa.MetaData())
    (ix,) = table.indexes
    assert ix.name is not None
    assert len(ix.name) <= 63
    again = build_table(info, sa.MetaData())
    assert next(iter(again.indexes)).name == ix.name
    short = build_table(_info(_field("UPDDATETIME", "TIMESTAMP")), sa.MetaData())
    assert next(iter(short.indexes)).name == "ix_prg_relatie_upddatetime"


def test_has_incremental_column() -> None:
    assert has_incremental_column(_info(_field("UPDDATETIME", "TIMESTAMP")))
    assert has_incremental_column(_info(_field("UpdDateTime", "TIMESTAMP")))
    assert not has_incremental_column(_info(_field("NAAM")))


def test_not_in_base_metadata() -> None:
    before = set(Base.metadata.tables)
    build_table(_info(), sa.MetaData())
    assert set(Base.metadata.tables) == before


@pytest.mark.parametrize("bad", ["a;drop", "1abc", "has space", 'q"uote', "", "naam-x", "é", "a" * 64])
def test_rejects_unsafe_column_name(bad: str) -> None:
    with pytest.raises(BrixxError):
        build_table(_info(_field(bad)), sa.MetaData())


@pytest.mark.parametrize("bad", ["x; drop table y", "brixx.t", "1t", "", "t" * 64])
def test_rejects_unsafe_table_name(bad: str) -> None:
    with pytest.raises(BrixxError):
        build_table(_info(name=bad), sa.MetaData())


def test_rejects_unsafe_primary_key() -> None:
    with pytest.raises(BrixxError):
        build_table(BrixxTable("T", "a;b", (_field("a;b"),)), sa.MetaData())


@pytest.mark.parametrize("name", ["company_id", "COMPANY_ID", "_synced_at", "_deleted_at", "_extra"])
def test_rejects_system_column_collision(name: str) -> None:
    with pytest.raises(BrixxError):
        build_table(_info(_field(name)), sa.MetaData())


def test_rejects_duplicate_columns_after_lowercasing() -> None:
    with pytest.raises(BrixxError):
        build_table(_info(_field("NAAM"), _field("naam")), sa.MetaData())


def test_rejects_missing_primary_key_field() -> None:
    with pytest.raises(BrixxError):
        build_table(BrixxTable("T", "ID", (_field("NAAM"),)), sa.MetaData())

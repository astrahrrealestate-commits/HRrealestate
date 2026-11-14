"""Snapshot -> Alembic migration: deterministic source, valid Postgres DDL offline, delta-only on later runs."""

import io
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.channels.brixx.models import BrixxField, BrixxTable
from app.channels.brixx.snapshot import read_snapshot
from app.core.errors import BrixxError
from app.dev.brixx_codegen import existing_mirror, mirror_spec, plan_delta, render_migration

EXAMPLE = Path(__file__).parents[2] / "fixtures" / "brixx" / "metadata_example"
WHEN = datetime(2026, 11, 3, 9, 30, tzinfo=UTC)


def _render(tables: list[BrixxTable], existing: dict[str, dict[str, str]] | None = None) -> str:
    delta = plan_delta(tables, existing or {})
    return render_migration(delta, revision="0030", down_revision="0029", create_date=WHEN)


def _module(source: str) -> types.ModuleType:
    module = types.ModuleType("generated_migration")
    exec(compile(source, "generated_migration.py", "exec"), module.__dict__)  # noqa: S102  (our own generated code)
    return module


def _offline_sql(source: str, step: str) -> str:
    """Run upgrade()/downgrade() in Alembic offline mode against the Postgres dialect and return the SQL."""
    buffer = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer})
    with Operations.context(context):
        getattr(_module(source), step)()
    return buffer.getvalue()


def test_first_migration_creates_schema_tables_and_indexes() -> None:
    source = _render(read_snapshot(EXAMPLE))
    module = _module(source)
    assert (module.revision, module.down_revision) == ("0030", "0029")
    sql = _offline_sql(source, "upgrade")
    assert sql.index("CREATE SCHEMA IF NOT EXISTS brixx") < sql.index("CREATE TABLE brixx.prg_object")
    for table in ("prg_object", "prg_relatie", "sys_land", "zprg_relatie"):
        assert f"CREATE TABLE brixx.{table} (" in sql
    assert "PRIMARY KEY (company_id, prg_relatieid)" in sql
    assert "_extra JSONB" in sql
    assert "CREATE INDEX ix_prg_relatie_objectid ON brixx.prg_relatie (objectid)" in sql
    assert "CREATE INDEX ix_sys_land" not in sql  # no FK and no UPDDATETIME: no index
    assert "op.create_table('prg_object'" in source


def test_first_migration_downgrade_drops_everything_it_created() -> None:
    sql = _offline_sql(_render(read_snapshot(EXAMPLE)), "downgrade")
    for table in ("prg_object", "prg_relatie", "sys_land", "zprg_relatie"):
        assert f"DROP TABLE brixx.{table}" in sql
    assert sql.rstrip().endswith("DROP SCHEMA IF EXISTS brixx;")


def test_output_is_deterministic_and_independent_of_input_order() -> None:
    tables = read_snapshot(EXAMPLE)
    assert _render(tables) == _render(list(reversed(tables)))
    assert "please adjust" not in _render(tables)


def test_generated_marker_lists_what_the_revision_creates() -> None:
    tables = read_snapshot(EXAMPLE)
    source = _render(tables)
    assert existing_mirror([source]) == mirror_spec(tables)
    assert mirror_spec(tables)["prg_relatie"]["naam"] == "VARCHAR(132)"
    assert mirror_spec(tables)["prg_relatie"]["upddatetime"] == "TIMESTAMP WITH TIME ZONE"
    assert "company_id" not in mirror_spec(tables)["prg_relatie"]  # system columns are not BRIXX columns


def test_existing_mirror_ignores_hand_written_migrations() -> None:
    assert existing_mirror(['"""plain"""\nrevision: str = "0001"\n']) == {}


def test_a_second_run_on_the_same_snapshot_has_nothing_to_emit() -> None:
    tables = read_snapshot(EXAMPLE)
    delta = plan_delta(tables, existing_mirror([_render(tables)]))
    assert delta.empty


def test_delta_adds_only_new_tables_and_columns() -> None:
    tables = read_snapshot(EXAMPLE)
    existing = existing_mirror([_render(tables)])
    land = next(t for t in tables if t.name == "SYS_LAND")
    grown = BrixxTable(
        land.name, land.primary_key, (*land.fields, BrixxField(9, "ISO2", "VARCHAR(2)", False, None, None))
    )
    added = BrixxTable("PRG_CONTRACT", "PRG_CONTRACTID", (BrixxField(1, "PRG_CONTRACTID", "NUMBER", True, None, None),))
    snapshot = [*(t for t in tables if t.name != "SYS_LAND"), grown, added]
    source = _render(snapshot, existing)
    sql = _offline_sql(source, "upgrade")
    assert "CREATE TABLE brixx.prg_contract" in sql
    assert "ALTER TABLE brixx.sys_land ADD COLUMN iso2 VARCHAR(2)" in sql
    assert "CREATE TABLE brixx.prg_object" not in sql  # never re-creates what a previous revision made
    assert set(existing_mirror([source])) == {"prg_contract", "sys_land"}
    down = _offline_sql(source, "downgrade")
    assert "ALTER TABLE brixx.sys_land DROP COLUMN iso2" in down
    assert "DROP TABLE brixx.prg_contract" in down
    assert "DROP SCHEMA" not in down  # only the first revision owns the schema


def test_a_changed_column_type_is_refused_with_table_and_column() -> None:
    tables = read_snapshot(EXAMPLE)
    existing = existing_mirror([_render(tables)])
    land = next(t for t in tables if t.name == "SYS_LAND")
    widened = tuple(
        BrixxField(f.id, f.name, "VARCHAR(10)" if f.name == "CODE" else f.type, f.required, None, None)
        for f in land.fields
    )
    with pytest.raises(BrixxError, match=r"sys_land\.code"):
        plan_delta([BrixxTable(land.name, land.primary_key, widened)], existing)


def test_an_unsafe_snapshot_table_is_refused() -> None:
    bad = BrixxTable(
        "PRG_BAD",
        "ID",
        (BrixxField(1, "ID", "NUMBER", True, None, None), BrixxField(2, "company_id", "NUMBER", False, None, None)),
    )
    with pytest.raises(BrixxError, match="system column"):
        plan_delta([bad], {})

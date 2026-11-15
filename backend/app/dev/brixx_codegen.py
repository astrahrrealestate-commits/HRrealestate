"""BRIXX metadata snapshot -> Alembic revision that creates the typed mirror tables (dev tooling, never at runtime).

Tables come from the same `build_table` the sync uses; Alembic renders the operations. Every generated revision carries
a `BRIXX_MIRROR` literal (table -> column -> Postgres type) of what it creates. The next run reads those literals from
the versions directory (as source, never imported) and emits only the delta: new tables and new columns. A column
whose type changed is refused (that needs a hand-written migration), and an unchanged snapshot emits nothing.
"""

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import sqlalchemy as sa
from alembic.autogenerate import render_python_code
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext

from app.channels.brixx.models import BrixxTable
from app.core.errors import BrixxError
from app.core.logging import get_logger
from app.directory.brixx.schema import MIRROR_SCHEMA, SYSTEM_COLUMNS, build_table

MARKER = "BRIXX_MIRROR"
Mirror = dict[str, dict[str, str]]
_CONTEXT = MigrationContext.configure(dialect_name="postgresql")  # offline: no database
_DIALECT = _CONTEXT.dialect

log = get_logger(__name__)


@dataclass(frozen=True)
class MirrorDelta:
    tables: tuple[sa.Table, ...]  # every snapshot table, built (lookup for the two lists below)
    new_tables: tuple[str, ...]
    new_columns: tuple[tuple[str, tuple[str, ...]], ...]  # (table, columns) for tables an earlier revision made
    first: bool  # no earlier revision: this one creates (and its downgrade drops) the schema

    @property
    def empty(self) -> bool:
        return not self.new_tables and not self.new_columns

    def spec(self) -> Mirror:
        """What this revision creates, for its `BRIXX_MIRROR` literal."""
        built = {t.name: _columns(t) for t in self.tables}
        out: Mirror = {name: built[name] for name in self.new_tables}
        for name, columns in self.new_columns:
            out[name] = {c: built[name][c] for c in columns}
        return dict(sorted(out.items()))


def _columns(table: sa.Table) -> dict[str, str]:
    """BRIXX columns of a mirror table (system columns excluded) with their compiled Postgres type."""
    return {c.name: c.type.compile(dialect=_DIALECT) for c in table.c if c.name not in SYSTEM_COLUMNS}


def _resolve_primary_key(info: BrixxTable) -> str | None:
    """BRIXX's real primary key, or `None` when it cannot be determined.

    BRIXX's `Z*` historical tables always return an empty `primaryKeyField`; most (verified against the real
    API) follow the documented `<table>ID` convention, but a minority instead repeat the non-Z table's own PK
    name (e.g. `ZPRG_CONTRACTGARANTSTELLER` has field `PRG_CONTRACTGARANTSTELLERID`, not
    `ZPRG_CONTRACTGARANTSTELLERID`) and so cannot be guessed; those are left out rather than guessed wrong."""
    names = {f.name.lower() for f in info.fields}
    if info.primary_key and info.primary_key.lower() in names:
        return info.primary_key
    fallback = f"{info.name}ID"
    return fallback if fallback.lower() in names else None


def _built(tables: Sequence[BrixxTable]) -> list[sa.Table]:
    metadata = sa.MetaData()
    usable = []
    for info in tables:
        pk = _resolve_primary_key(info)
        if pk is None:
            log.warning("brixx.codegen_skipped", table=info.name, reason="no_usable_primary_key")
            continue
        usable.append(info if pk == info.primary_key else replace(info, primary_key=pk))
    return sorted((build_table(info, metadata) for info in usable), key=lambda t: t.name)


def mirror_spec(tables: Sequence[BrixxTable]) -> Mirror:
    return {t.name: _columns(t) for t in _built(tables)}


def existing_mirror(sources: Iterable[str]) -> Mirror:
    """Merge the `BRIXX_MIRROR` literals of earlier revisions (migration file sources; others are ignored)."""
    merged: Mirror = {}
    for source in sources:
        for table, columns in _marker(source).items():
            merged.setdefault(table, {}).update(columns)
    return merged


def _marker(source: str) -> Mirror:
    for node in ast.parse(source).body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == MARKER and isinstance(node, ast.AnnAssign) and node.value:
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
                raise BrixxError(f"malformed {MARKER} literal in a migration")
            return {str(k): {str(c): str(t) for c, t in v.items()} for k, v in value.items()}
    return {}


def plan_delta(tables: Sequence[BrixxTable], existing: Mirror) -> MirrorDelta:
    """New tables and columns of the snapshot versus earlier revisions; a changed column type is refused."""
    built = _built(tables)
    new_tables: list[str] = []
    new_columns: list[tuple[str, tuple[str, ...]]] = []
    changed: list[str] = []
    for table in built:
        known = existing.get(table.name)
        if known is None:
            new_tables.append(table.name)
            continue
        columns = _columns(table)
        changed.extend(f"{table.name}.{c}" for c, kind in columns.items() if c in known and known[c] != kind)
        added = tuple(c for c in columns if c not in known)
        if added:
            new_columns.append((table.name, added))
    if changed:
        raise BrixxError(
            f"column type changed for {', '.join(changed)}: write that migration by hand, then rerun codegen"
        )
    return MirrorDelta(tuple(built), tuple(new_tables), tuple(new_columns), first=not existing)


def _operations(delta: MirrorDelta) -> list[ops.MigrateOperation]:
    by_name = {t.name: t for t in delta.tables}
    out: list[ops.MigrateOperation] = []
    for name in delta.new_tables:
        table = by_name[name]
        out.append(ops.CreateTableOp.from_table(table))
        out.extend(ops.CreateIndexOp.from_index(i) for i in sorted(table.indexes, key=lambda i: str(i.name)))
    for name, columns in delta.new_columns:
        table = by_name[name]
        for column in (table.c[c] for c in columns):
            fresh = sa.Column(column.name, column.type, nullable=column.nullable)  # unbound copy for the op
            out.append(ops.AddColumnOp.from_column_and_tablename(MIRROR_SCHEMA, name, fresh))
        indexes = [i for i in table.indexes if {c.name for c in i.columns} <= set(columns)]
        out.extend(ops.CreateIndexOp.from_index(i) for i in sorted(indexes, key=lambda i: str(i.name)))
    return out


def _code(directive: ops.UpgradeOps | ops.DowngradeOps) -> str:
    rendered = render_python_code(directive, migration_context=_CONTEXT)
    return "\n".join(line for line in rendered.splitlines() if not line.strip().startswith("# ###"))


def _marker_source(spec: Mirror) -> str:
    lines = [f"{MARKER}: dict[str, dict[str, str]] = {{"]
    for table, columns in spec.items():
        lines.append(f'    "{table}": {{')
        lines.extend(f'        "{column}": "{kind}",' for column, kind in sorted(columns.items()))
        lines.append("    },")
    return "\n".join([*lines, "}"])


_POSTGRESQL_IMPORT = "from sqlalchemy.dialects import postgresql\n"
_HEADER = '''"""{message}

Revision ID: {revision}
Revises: {down_revision}
Create Date: {create_date}

Generated by `python -m app.dev.brixx codegen` from the BRIXX metadata snapshot (tests/fixtures/brixx/metadata).
Do not edit: BRIXX changes get a new revision from the next codegen run, which reads {marker} to emit the delta.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
{imports}
revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirror columns this revision creates (table -> column -> Postgres type); read as source by the codegen.
'''


def render_migration(delta: MirrorDelta, *, revision: str, down_revision: str, create_date: datetime) -> str:
    """The revision file's source. Identical inputs give identical bytes (`create_date` is the only clock)."""
    if delta.empty:
        raise BrixxError("the mirror migrations already match the snapshot: nothing to generate")
    body = _operations(delta)
    upgrade = _code(ops.UpgradeOps(ops=[ops.ExecuteSQLOp(f"CREATE SCHEMA IF NOT EXISTS {MIRROR_SCHEMA}"), *body]))
    drop_schema = [ops.ExecuteSQLOp(f"DROP SCHEMA IF EXISTS {MIRROR_SCHEMA}")] if delta.first else []
    downgrade = _code(ops.DowngradeOps(ops=[*ops.UpgradeOps(ops=body).reverse().ops, *drop_schema]))
    header = _HEADER.format(
        message=_message(delta),
        revision=revision,
        down_revision=down_revision,
        create_date=create_date.strftime("%Y-%m-%d %H:%M:%S"),
        marker=MARKER,
        imports=_POSTGRESQL_IMPORT if "postgresql." in upgrade + downgrade else "",
    )
    marker = _marker_source(delta.spec())
    return f"{header}{marker}\n\n\ndef upgrade() -> None:\n{upgrade}\n\n\ndef downgrade() -> None:\n{downgrade}\n"


def _message(delta: MirrorDelta) -> str:
    if delta.first:
        return f"brixx mirror: {len(delta.new_tables)} tables from the metadata snapshot"
    added = sum(len(columns) for _table, columns in delta.new_columns)
    return f"brixx mirror delta: {len(delta.new_tables)} new tables, {added} new columns"

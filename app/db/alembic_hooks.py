"""Autogenerate post-processing for VARCHAR+CHECK enums.

Alembic renders `sa.Enum(native_enum=False, create_constraint=True)` columns with duplicate, inconsistently named CHECK
constraints. This hook rewrites every new enum column to `sa.String` and emits exactly one
`CHECK (<col> IN (...))` named `ck_<table>_<column>` — the same name the metadata naming convention produces, so the
models and the database agree (guarded by tests/integration/test_migrations.py).
"""

import re
from typing import Any, TypeGuard

import sqlalchemy as sa
from alembic.operations import ops
from sqlalchemy.sql.elements import conv


def _check_op(table: str, column: sa.Column[Any], schema: str | None) -> ops.CreateCheckConstraintOp:
    enum_type = column.type
    if not isinstance(enum_type, sa.Enum):
        raise TypeError(f"{table}.{column.name} is not an Enum column")
    values = ", ".join(f"'{v}'" for v in enum_type.enums)
    return ops.CreateCheckConstraintOp(
        conv(f"ck_{table}_{column.name}"), table, f"{column.name} IN ({values})", schema=schema
    )


def _is_enum(column: Any) -> TypeGuard[sa.Column[Any]]:
    return isinstance(column, sa.Column) and isinstance(column.type, sa.Enum) and not column.type.native_enum


def _checks_enum(check: sa.CheckConstraint, enum_cols: dict[str, Any]) -> bool:
    """True for the CHECKs SQLAlchemy derives from enum columns (`[table.]col IN (...)`)."""
    sql = str(check.sqltext)
    return any(re.match(rf"^(\w+\.)?{re.escape(name)} IN \(", sql) for name in enum_cols)


def _as_string(column: sa.Column[Any]) -> sa.Column[Any]:
    """Copy of an enum column typed VARCHAR. The original belongs to the live model metadata and must not change."""
    enum_type = column.type
    length = enum_type.length if isinstance(enum_type, sa.Enum) and enum_type.length else 32
    default = column.server_default
    server_default = sa.DefaultClause(default.arg) if isinstance(default, sa.DefaultClause) else None
    # A fresh Column, not column._copy(): a copied Enum type re-attaches its own inline CHECK when rendered.
    return sa.Column(column.name, sa.String(length=length), nullable=column.nullable, server_default=server_default)


def _rewrite(container: ops.OpContainer) -> list[ops.MigrateOperation]:
    checks: list[ops.MigrateOperation] = []
    for op_ in container.ops:
        if isinstance(op_, ops.CreateTableOp):
            enum_cols: dict[str, sa.Column[Any]] = {c.name: c for c in op_.columns if _is_enum(c)}
            kept: list[Any] = []
            for item in op_.columns:
                if isinstance(item, sa.CheckConstraint) and _checks_enum(item, enum_cols):
                    continue
                kept.append(item)
            for col in enum_cols.values():
                checks.append(_check_op(op_.table_name, col, op_.schema))
            op_.columns = [_as_string(c) if _is_enum(c) else c for c in kept]
        elif isinstance(op_, ops.AddColumnOp) and _is_enum(op_.column):
            checks.append(_check_op(op_.table_name, op_.column, op_.schema))
            op_.column = _as_string(op_.column)
        elif isinstance(op_, ops.OpContainer):
            checks.extend(_rewrite(op_))
    return checks


def normalise_enum_checks(context: Any, revision: Any, directives: list[Any]) -> None:
    """`process_revision_directives` hook for env.py."""
    script = directives[0]
    for upgrade_ops in script.upgrade_ops_list:
        upgrade_ops.ops.extend(_rewrite(upgrade_ops))

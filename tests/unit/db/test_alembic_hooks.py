from enum import StrEnum
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from alembic.operations import ops

from app.db.alembic_hooks import normalise_enum_checks
from app.db.base import NAMING_CONVENTION, str_enum


class Colour(StrEnum):
    red = "red"
    blue = "blue"


def _run(upgrade: ops.UpgradeOps) -> list[Any]:
    script = SimpleNamespace(upgrade_ops_list=[upgrade])
    normalise_enum_checks(None, None, [script])
    return upgrade.ops


def test_create_table_gets_one_named_check_per_enum_and_sources_untouched() -> None:
    md = sa.MetaData(naming_convention=NAMING_CONVENTION)
    table = sa.Table(
        "things",
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("a", str_enum(Colour)),
        sa.Column("b", str_enum(Colour), nullable=True),
    )
    result = _run(ops.UpgradeOps(ops=[ops.CreateTableOp.from_table(table)]))

    create = next(o for o in result if isinstance(o, ops.CreateTableOp))
    checks = [o for o in result if isinstance(o, ops.CreateCheckConstraintOp)]
    assert sorted(str(c.constraint_name) for c in checks) == ["ck_things_a", "ck_things_b"]
    assert all("'red', 'blue'" in str(c.condition) for c in checks)
    assert not [c for c in create.columns if isinstance(c, sa.CheckConstraint)]
    rendered = {c.name: c.type for c in create.columns if isinstance(c, sa.Column)}
    assert isinstance(rendered["a"], sa.String)
    assert not isinstance(rendered["a"], sa.Enum)
    assert isinstance(table.c.a.type, sa.Enum), "hook must not mutate the model's columns"
    assert isinstance(table.c.b.type, sa.Enum)


def test_add_column_inside_modify_table_ops() -> None:
    md = sa.MetaData(naming_convention=NAMING_CONVENTION)
    table = sa.Table("things", md, sa.Column("id", sa.Integer, primary_key=True), sa.Column("c", str_enum(Colour)))
    add = ops.AddColumnOp("things", table.c.c)
    result = _run(ops.UpgradeOps(ops=[ops.ModifyTableOps("things", [add])]))

    checks = [o for o in result if isinstance(o, ops.CreateCheckConstraintOp)]
    assert [str(c.constraint_name) for c in checks] == ["ck_things_c"]
    modify = next(o for o in result if isinstance(o, ops.ModifyTableOps))
    new_add = next(o for o in modify.ops if isinstance(o, ops.AddColumnOp))
    assert isinstance(new_add.column.type, sa.String)
    assert not isinstance(new_add.column.type, sa.Enum)
    assert isinstance(table.c.c.type, sa.Enum), "hook must not mutate the model's columns"


def test_rendered_create_table_has_no_inline_enum_check() -> None:
    from alembic.autogenerate import render_python_code

    md = sa.MetaData(naming_convention=NAMING_CONVENTION)
    table = sa.Table(
        "things",
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("a", str_enum(Colour), server_default="red"),
    )
    upgrade = ops.UpgradeOps(ops=[ops.CreateTableOp.from_table(table)])
    _run(upgrade)
    code = render_python_code(upgrade)
    assert "CheckConstraint" not in code
    assert "sa.Enum" not in code
    assert "server_default='red'" in code
    assert "op.create_check_constraint(op.f('ck_things_a')" in code

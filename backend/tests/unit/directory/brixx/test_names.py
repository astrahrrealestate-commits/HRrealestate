"""The names the code reads must be the names BRIXX really sends (the `BRIXX_MIRROR` literals of the migrations)."""

import ast
import re
from pathlib import Path

import pytest

from app.dev.brixx_codegen import existing_mirror
from app.directory.brixx.names import READS

BACKEND = Path(__file__).resolve().parents[4]
VERSIONS = BACKEND / "app/db/alembic/versions"
REAL = existing_mirror(p.read_text() for p in sorted(VERSIONS.glob("*.py")))
NAME = re.compile(r"^[a-z][a-z0-9_]*$")
READERS = {"pick", "pick_text", "pick_int", "pick_date", "is_flagged"}


def _is_names(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Tuple)
        and bool(node.elts)
        and all(isinstance(e, ast.Constant) and isinstance(e.value, str) and NAME.match(e.value) for e in node.elts)
    )


def _names(node: ast.expr) -> tuple[str, ...]:
    return tuple(e.value for e in node.elts if isinstance(e, ast.Constant))  # type: ignore[attr-defined]


def _sources() -> list[Path]:
    brixx = sorted((BACKEND / "app/directory/brixx").glob("*.py"))
    return [*brixx, BACKEND / "app/api/maintenance/brixx_tickets.py"]


def _code_groups() -> dict[tuple[str, ...], str]:
    """Every column group the code reads: literal tuples handed to a reader, and module-level `NAME = ("a", "b")`."""
    found: dict[tuple[str, ...], str] = {}
    for path in _sources():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                for arg in node.args if called in READERS else []:
                    if _is_names(arg):
                        found[_names(arg)] = f"{path.name}:{node.lineno}"
        for node in tree.body:
            single = isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            if isinstance(node, ast.Assign) and single and _is_names(node.value):
                found[_names(node.value)] = f"{path.name}:{node.lineno}"
    return found


def _listed() -> set[tuple[str, ...]]:
    return {group for groups in READS.values() for group in groups}


def test_the_real_schema_snapshot_is_loaded() -> None:
    assert len(REAL) > 300
    assert "prg_subobject" in REAL


@pytest.mark.parametrize("table", sorted(READS))
def test_every_table_the_code_reads_exists(table: str) -> None:
    assert table in REAL, f"BRIXX has no table {table!r}"


@pytest.mark.parametrize("table", sorted(READS))
def test_every_column_group_has_a_real_column_in_its_table(table: str) -> None:
    columns = set(REAL.get(table, {}))
    missing = [group for group in READS[table] if not columns & set(group)]
    assert not missing, f"{table} has none of these columns: {missing}"


@pytest.mark.parametrize("table", sorted(READS))
def test_the_first_candidate_of_a_group_is_a_real_name_somewhere(table: str) -> None:
    """The first name is the one BRIXX sends; later ones are tolerated aliases and must not be the only match."""
    real_anywhere = {column for columns in REAL.values() for column in columns}
    stale = [group for group in READS[table] if group[0] not in real_anywhere]
    assert not stale, f"{table}: the leading name of these groups is not a real BRIXX column: {stale}"


def test_every_column_group_the_code_reads_is_listed_in_names() -> None:
    unlisted = {where: group for group, where in _code_groups().items() if group not in _listed()}
    assert not unlisted, f"read but not listed in app/directory/brixx/names.py: {unlisted}"


def test_every_listed_group_is_still_read_by_the_code() -> None:
    code = set(_code_groups())
    stale = [group for group in _listed() if group not in code and len(group) > 1]
    assert not stale, f"listed in names.py but no longer read: {stale}"

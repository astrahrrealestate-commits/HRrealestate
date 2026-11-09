"""BRIXX metadata snapshot: stable JSON per table plus an index, round-tripping to `BrixxTable`."""

import json
from pathlib import Path

import pytest

from app.channels.brixx.fake import FakeBrixxApi, FakeTable
from app.channels.brixx.models import BrixxField, BrixxTable
from app.channels.brixx.snapshot import (
    INDEX_FILE,
    dump_table,
    load_table,
    read_snapshot,
    record_snapshot,
    write_snapshot,
)
from app.core.errors import BrixxError

EXAMPLE = Path(__file__).parents[3] / "fixtures" / "brixx" / "metadata_example"


def _object() -> BrixxTable:
    return BrixxTable(
        "PRG_OBJECT",
        "PRG_OBJECTID",
        (
            BrixxField(2, "NAAM", "VARCHAR(80)", False, None, None),
            BrixxField(1, "PRG_OBJECTID", "NUMBER", True, None, None),
        ),
    )


def _relatie() -> BrixxTable:
    return BrixxTable(
        "PRG_RELATIE",
        "PRG_RELATIEID",
        (
            BrixxField(1, "PRG_RELATIEID", "NUMBER", True, None, None),
            BrixxField(2, "OBJECTID", "NUMBER", False, "PRG_OBJECT", "PRG_OBJECTID"),
        ),
    )


def test_dump_is_sorted_by_field_id_and_round_trips() -> None:
    text = dump_table(_object())
    assert text.endswith("\n")
    data = json.loads(text)
    assert [f["id"] for f in data["fields"]] == [1, 2]
    by_id = tuple(sorted(_object().fields, key=lambda f: f.id))
    assert load_table(json.loads(text)) == BrixxTable("PRG_OBJECT", "PRG_OBJECTID", by_id)
    assert dump_table(load_table(data)) == text


def test_dump_is_deterministic_regardless_of_field_order() -> None:
    reordered = BrixxTable(_object().name, _object().primary_key, tuple(reversed(_object().fields)))
    assert dump_table(reordered) == dump_table(_object())


def test_write_then_read_returns_tables_sorted_by_name(tmp_path: Path) -> None:
    written = write_snapshot(tmp_path, [_relatie(), _object()], environment="hrrealestate")
    assert {p.name for p in written} == {INDEX_FILE, "PRG_OBJECT.json", "PRG_RELATIE.json"}
    index = json.loads((tmp_path / INDEX_FILE).read_text(encoding="utf-8"))
    assert index["tables"] == ["PRG_OBJECT", "PRG_RELATIE"]
    assert index["environment"] == "hrrealestate"
    assert [t.name for t in read_snapshot(tmp_path)] == ["PRG_OBJECT", "PRG_RELATIE"]
    assert read_snapshot(tmp_path)[1] == _relatie()


def test_write_refuses_an_existing_snapshot_unless_forced(tmp_path: Path) -> None:
    write_snapshot(tmp_path, [_object(), _relatie()], environment="hrrealestate")
    with pytest.raises(BrixxError, match="already holds a snapshot"):
        write_snapshot(tmp_path, [_object()], environment="hrrealestate")
    write_snapshot(tmp_path, [_object()], environment="hrrealestate", force=True)
    assert [t.name for t in read_snapshot(tmp_path)] == ["PRG_OBJECT"]
    assert not (tmp_path / "PRG_RELATIE.json").exists()  # a table BRIXX no longer lists leaves no stale file


@pytest.mark.parametrize("name", ["../evil", "A/B", "", "1ABC", "x" * 64])
def test_unsafe_table_names_never_become_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(BrixxError, match="unsafe BRIXX table name"):
        write_snapshot(tmp_path, [BrixxTable(name, "ID", ())], environment="hrrealestate")
    assert list(tmp_path.iterdir()) == []


def test_read_rejects_a_file_whose_table_name_does_not_match(tmp_path: Path) -> None:
    write_snapshot(tmp_path, [_object()], environment="hrrealestate")
    (tmp_path / "PRG_OBJECT.json").write_text(dump_table(_relatie()), encoding="utf-8")
    with pytest.raises(BrixxError, match="PRG_OBJECT"):
        read_snapshot(tmp_path)


def test_read_reports_a_missing_snapshot_clearly(tmp_path: Path) -> None:
    with pytest.raises(BrixxError, match="no BRIXX metadata snapshot"):
        read_snapshot(tmp_path / "absent")


def test_load_rejects_malformed_fields() -> None:
    with pytest.raises(BrixxError, match="malformed"):
        load_table({"name": "PRG_X", "primary_key": "ID", "fields": [{"id": "x"}]})


def test_record_describes_every_listed_table_sorted() -> None:
    tables = {"PRG_RELATIE": FakeTable(_relatie(), [{"PRG_RELATIEID": 1}]), "PRG_OBJECT": FakeTable(_object(), [])}
    api = FakeBrixxApi(tables)
    recorded = record_snapshot(api)
    assert [t.name for t in recorded] == ["PRG_OBJECT", "PRG_RELATIE"]
    assert api.fetch_log == []  # metadata only: never a data page


def test_committed_example_snapshot_is_in_canonical_form(tmp_path: Path) -> None:
    tables = read_snapshot(EXAMPLE)
    assert tables, "example snapshot must hold tables"
    write_snapshot(tmp_path, tables, environment=json.loads((EXAMPLE / INDEX_FILE).read_text("utf-8"))["environment"])
    for path in sorted(EXAMPLE.glob("*.json")):
        assert (tmp_path / path.name).read_text(encoding="utf-8") == path.read_text(encoding="utf-8"), path.name

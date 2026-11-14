"""BRIXX metadata snapshot: one JSON file per table plus `_index.json`, stable and diff-friendly.

A snapshot holds metadata only (table names, primary keys, field ids, names, types, required flags, foreign keys):
never row data, never the token. Files are written with sorted keys, fields sorted by id, two-space indent and a
trailing newline, so recording the same metadata twice yields identical bytes. Table names become file names, so they
are validated as identifiers first. The index lists the tables; readers trust only the index.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.channels.brixx.models import BrixxField, BrixxTable
from app.channels.brixx.ports import BrixxApi
from app.core.errors import BrixxError

INDEX_FILE = "_index.json"
FORMAT_VERSION = 1
_TABLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def record_snapshot(api: BrixxApi) -> list[BrixxTable]:
    """Describe every table the token can read, sorted by name. Calls only the metadata endpoints."""
    names = sorted({name for name, _key in api.list_tables()})
    return [api.describe_table(name) for name in names]


def dump_table(info: BrixxTable) -> str:
    fields = sorted(info.fields, key=lambda f: (f.id, f.name))
    data = {
        "name": info.name,
        "primary_key": info.primary_key,
        "fields": [
            {
                "id": f.id,
                "name": f.name,
                "type": f.type,
                "required": f.required,
                "fk_table": f.fk_table,
                "fk_field": f.fk_field,
            }
            for f in fields
        ],
    }
    return _dumps(data)


def load_table(data: dict[str, Any]) -> BrixxTable:
    """A `BrixxTable` from its snapshot JSON; anything malformed is a `BrixxError` (never a KeyError/TypeError)."""
    try:
        fields = tuple(_load_field(f) for f in data["fields"])
        return BrixxTable(_text(data["name"]), _text(data["primary_key"]), tuple(sorted(fields, key=lambda f: f.id)))
    except (KeyError, TypeError, ValueError) as exc:
        raise BrixxError("malformed BRIXX metadata snapshot entry") from exc


def write_snapshot(
    directory: Path, tables: Sequence[BrixxTable], *, environment: str, force: bool = False
) -> list[Path]:
    """Write the snapshot; refuses to replace an existing one unless `force` (then stale table files are removed)."""
    ordered = sorted(tables, key=lambda t: t.name)
    for info in ordered:
        _check_name(info.name)
    index = directory / INDEX_FILE
    if index.exists() and not force:
        raise BrixxError(f"{directory} already holds a snapshot; pass --force to re-record it")
    previous = _listed(directory) if index.exists() else []
    directory.mkdir(parents=True, exist_ok=True)
    written = [directory / INDEX_FILE]
    for info in ordered:
        path = directory / f"{info.name}.json"
        path.write_text(dump_table(info), encoding="utf-8")
        written.append(path)
    keep = {t.name for t in ordered}
    for stale in previous:
        if stale not in keep:
            (directory / f"{stale}.json").unlink(missing_ok=True)
    index_data = {"format": FORMAT_VERSION, "environment": environment, "tables": [t.name for t in ordered]}
    index.write_text(_dumps(index_data), encoding="utf-8")
    return written


def read_snapshot(directory: Path) -> list[BrixxTable]:
    """The snapshot's tables sorted by name, each checked against the name the index gives it."""
    if not (directory / INDEX_FILE).is_file():
        raise BrixxError(f"no BRIXX metadata snapshot in {directory} (run the discover command first)")
    tables = []
    for name in sorted(_listed(directory)):
        info = load_table(_read_json(directory / f"{name}.json"))
        if info.name != name:
            raise BrixxError(f"snapshot file {name}.json describes a different table")
        tables.append(info)
    return tables


def _listed(directory: Path) -> list[str]:
    index = _read_json(directory / INDEX_FILE)
    if index.get("format") != FORMAT_VERSION or not isinstance(index.get("tables"), list):
        raise BrixxError(f"unsupported BRIXX snapshot index in {directory}")
    names = [str(n) for n in index["tables"]]
    for name in names:
        _check_name(name)
    return names


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BrixxError(f"cannot read BRIXX snapshot file {path.name}") from exc
    if not isinstance(data, dict):
        raise BrixxError(f"BRIXX snapshot file {path.name} is not an object")
    return data


def _load_field(raw: dict[str, Any]) -> BrixxField:
    if not isinstance(raw["id"], int) or not isinstance(raw["required"], bool):
        raise ValueError("field id must be an int and required a bool")
    return BrixxField(
        id=raw["id"],
        name=_text(raw["name"]),
        type=_text(raw["type"]),
        required=raw["required"],
        fk_table=_optional(raw["fk_table"]),
        fk_field=_optional(raw["fk_field"]),
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def _optional(value: object) -> str | None:
    return None if value is None else _text(value)


def _check_name(name: str) -> None:
    if not _TABLE_NAME.fullmatch(name):
        raise BrixxError(f"unsafe BRIXX table name {name!r} in snapshot")


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

"""BRIXX API value objects: table metadata and one page of rows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrixxField:
    id: int
    name: str
    type: str
    required: bool
    fk_table: str | None
    fk_field: str | None


@dataclass(frozen=True)
class BrixxTable:
    name: str
    primary_key: str
    fields: tuple[BrixxField, ...]


@dataclass(frozen=True)
class BrixxPage:
    rows: list[dict[str, object]]
    page: int
    per_page: int
    has_next: bool

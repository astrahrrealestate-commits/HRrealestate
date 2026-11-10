"""In-memory BRIXX API for tests and dev: pages, `upddatetime` and keyset filters, projections, documents, scripted
failures."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.channels.brixx.models import BrixxPage, BrixxTable
from app.channels.brixx.normalise import normalise_row
from app.core.errors import BrixxError

_UPD_FILTER = re.compile(r"\[upddatetime >= (\d{4}-\d{2}-\d{2})\]", re.IGNORECASE)
_KEYSET_FILTER = re.compile(r"\[([A-Za-z][A-Za-z0-9_]*) > (-?\d+)\]")


@dataclass
class FakeTable:
    info: BrixxTable
    rows: list[dict[str, object]]


def _to_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _cell(row: dict[str, object], column: str) -> object:
    return next((v for k, v in row.items() if k.lower() == column), None)


def _sort_key(value: object, *, numeric: bool) -> tuple[bool, Any]:
    """NULLs last; numbers compare as numbers, anything else as text."""
    if value is None:
        return (True, 0)
    return (False, value if numeric else str(value))


def _upddatetime(row: dict[str, object]) -> object:
    return next((v for k, v in row.items() if k.lower() == "upddatetime"), None)


def _projected(
    table: FakeTable, rows: list[dict[str, object]], fields: tuple[str, ...] | None
) -> list[dict[str, object]]:
    """Keep only `fields` (case-insensitive, original key case), as BRIXX does for a `fields=` query."""
    if not fields:
        return rows
    wanted = {f.lower() for f in fields}
    if not wanted <= {f.name.lower() for f in table.info.fields}:
        raise BrixxError(f"BRIXX table {table.info.name} has no such field to return")
    return [{k: v for k, v in r.items() if k.lower() in wanted} for r in rows]


class FakeBrixxApi:
    def __init__(
        self,
        tables: dict[str, FakeTable],
        page_size: int = 50,
        documents: dict[int, bytes] | None = None,
    ) -> None:
        self._tables = {name.upper(): table for name, table in tables.items()}
        self._page_size = page_size
        self._documents = documents or {}
        self._failures: dict[tuple[str, int], tuple[BrixxError, bool]] = {}
        self._download_failures: dict[int, tuple[BrixxError, bool]] = {}
        self.download_log: list[int] = []
        self.fetch_log: list[tuple[str, int, str | None]] = []
        self.order_log: list[str | None] = []  # `order_by` of each fetch, parallel to `fetch_log`

    def fail_on(self, table: str, page: int, error: BrixxError, *, once: bool = True) -> None:
        """Raise `error` when `page` of `table` is fetched (once by default, so a retry succeeds)."""
        self._failures[(table.upper(), page)] = (error, once)

    def fail_download(self, document_id: int, error: BrixxError, *, once: bool = True) -> None:
        """Raise `error` when `document_id` is downloaded (once by default, so a retry succeeds)."""
        self._download_failures[document_id] = (error, once)

    def _table(self, name: str) -> FakeTable:
        try:
            return self._tables[name.upper()]
        except KeyError:
            raise BrixxError(f"unknown BRIXX table {name}") from None

    def list_tables(self) -> list[tuple[str, str]]:
        return [(t.info.name, t.info.primary_key) for t in self._tables.values()]

    def describe_table(self, name: str) -> BrixxTable:
        return self._table(name).info

    def fetch_page(
        self,
        table: str,
        *,
        page: int,
        filters: str | None = None,
        order_by: str | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> BrixxPage:
        self.fetch_log.append((table, page, filters))
        self.order_log.append(order_by)
        if page < 1:
            raise BrixxError("BRIXX pages start at 1")
        failure = self._failures.get((table.upper(), page))
        if failure is not None:
            error, once = failure
            if once:
                del self._failures[(table.upper(), page)]
            raise error
        fake_table = self._table(table)
        rows = self._ordered(fake_table, self._filtered(fake_table.rows, filters), order_by)
        start = (page - 1) * self._page_size
        chunk = _projected(fake_table, rows[start : start + self._page_size], fields)
        return BrixxPage(
            rows=[normalise_row(r) for r in chunk],
            page=page,
            per_page=self._page_size,
            has_next=start + self._page_size < len(rows),
        )

    @staticmethod
    def _ordered(table: FakeTable, rows: list[dict[str, object]], order_by: str | None) -> list[dict[str, object]]:
        """Sort by `order_by` (case-insensitive column of the table; numeric when every value is a number)."""
        if order_by is None:
            return rows
        column = order_by.strip().lower()
        if column not in {f.name.lower() for f in table.info.fields}:
            raise BrixxError(f"BRIXX table {table.info.name} has no column to order by")
        values = [_cell(r, column) for r in rows]
        numeric = all(isinstance(v, int | float | Decimal) and not isinstance(v, bool) for v in values if v is not None)
        order = sorted(range(len(rows)), key=lambda i: _sort_key(values[i], numeric=numeric))
        return [rows[i] for i in order]

    @staticmethod
    def _filtered(rows: list[dict[str, object]], filters: str | None) -> list[dict[str, object]]:
        if not filters:
            return rows
        keyset = _KEYSET_FILTER.fullmatch(filters.strip())
        if keyset is not None and keyset.group(1).lower() != "upddatetime":
            column, cursor = keyset.group(1).lower(), int(keyset.group(2))
            return [r for r in rows if (value := _cell(r, column)) is not None and int(str(value)) > cursor]
        match = _UPD_FILTER.fullmatch(filters.strip())
        since = _to_datetime(match.group(1)) if match else None
        if since is None:
            raise BrixxError("fake supports only [upddatetime >= yyyy-MM-dd] or [<integer column> > n]")
        return [r for r in rows if ((value := _to_datetime(_upddatetime(r))) is not None and value >= since)]

    def download_document(self, document_id: int) -> bytes:
        self.download_log.append(document_id)
        failure = self._download_failures.get(document_id)
        if failure is not None:
            error, once = failure
            if once:
                del self._download_failures[document_id]
            raise error
        try:
            return self._documents[document_id]
        except KeyError:
            raise BrixxError(f"unknown BRIXX document {document_id}") from None

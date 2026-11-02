"""In-memory BRIXX API for tests and dev: pages, a simple `upddatetime` filter, scripted failures."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.channels.brixx.models import BrixxPage, BrixxTable
from app.core.errors import BrixxError

_UPD_FILTER = re.compile(r"\[upddatetime\s*>=\s*([^\]\s]+)\s*\]", re.IGNORECASE)


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


def _upddatetime(row: dict[str, object]) -> object:
    return next((v for k, v in row.items() if k.lower() == "upddatetime"), None)


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
        self.fetch_log: list[tuple[str, int, str | None]] = []

    def fail_on(self, table: str, page: int, error: BrixxError, *, once: bool = True) -> None:
        """Raise `error` when `page` of `table` is fetched (once by default, so a retry succeeds)."""
        self._failures[(table.upper(), page)] = (error, once)

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
        self, table: str, *, page: int, filters: str | None = None, order_by: str | None = None
    ) -> BrixxPage:
        self.fetch_log.append((table, page, filters))
        failure = self._failures.get((table.upper(), page))
        if failure is not None:
            error, once = failure
            if once:
                del self._failures[(table.upper(), page)]
            raise error
        rows = self._filtered(self._table(table).rows, filters)
        start = (page - 1) * self._page_size
        chunk = rows[start : start + self._page_size]
        return BrixxPage(
            rows=[dict(r) for r in chunk],
            page=page,
            per_page=self._page_size,
            has_next=start + self._page_size < len(rows),
        )

    @staticmethod
    def _filtered(rows: list[dict[str, object]], filters: str | None) -> list[dict[str, object]]:
        match = _UPD_FILTER.search(filters or "")
        since = _to_datetime(match.group(1)) if match else None
        if since is None:
            return rows
        return [r for r in rows if ((value := _to_datetime(_upddatetime(r))) is not None and value >= since)]

    def download_document(self, document_id: int) -> bytes:
        try:
            return self._documents[document_id]
        except KeyError:
            raise BrixxError(f"unknown BRIXX document {document_id}") from None

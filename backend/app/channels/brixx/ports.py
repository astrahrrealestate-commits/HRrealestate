"""BRIXX ports: the read-only API the mirror depends on (real HTTP adapter and fake implement it)."""

from typing import Protocol

from app.channels.brixx.models import BrixxPage, BrixxTable
from app.core.errors import BrixxAuthError, BrixxError

__all__ = ["BrixxApi", "BrixxAuthError", "BrixxError"]


class BrixxApi(Protocol):
    def list_tables(self) -> list[tuple[str, str]]:
        """(table name, primary key) for every table the token can read."""
        ...

    def describe_table(self, name: str) -> BrixxTable: ...

    def fetch_page(
        self,
        table: str,
        *,
        page: int,
        filters: str | None = None,
        order_by: str | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> BrixxPage:
        """One page of rows. `fields` limits the columns (primary-key scans only; upserts need whole rows)."""
        ...

    def download_document(self, document_id: int) -> bytes: ...

"""BRIXX data mirror contracts: the sync run vocabularies and the `GET /api/v1/brixx/status` read model.

The status is read from the sync state tables only (never from BRIXX). Error texts are what the sync persisted: an
error class name plus table and page, never a message, URL, token or row value.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime

from app.contracts.common import Contract


class BrixxRunKind(StrEnum):
    incremental = "incremental"
    reconcile = "reconcile"


class BrixxRunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class BrixxRun(Contract):
    """The newest sync run (any status). `error` names the failed tables and error classes."""

    id: UUID
    kind: BrixxRunKind
    status: BrixxRunStatus
    started_at: AwareDatetime
    finished_at: AwareDatetime | None
    error: str | None


class BrixxTableStatus(Contract):
    """One mirrored table. `row_count` is the rows written by the table's latest run (an incremental run counts only
    changed rows). `last_success_at`: every BRIXX change before it is in the mirror; null before the table first
    completes, and for a table without UPDDATETIME also while a run is mid-table or failing."""

    name: str
    row_count: int
    last_success_at: AwareDatetime | None
    lag_seconds: int | None
    drifted: bool
    last_error: str | None


class BrixxStatus(Contract):
    """`stale` is true when no run succeeded within 3 x `brixx_sync_interval_minutes` (or none ever did)."""

    last_run: BrixxRun | None
    tables: list[BrixxTableStatus]
    total_rows: int
    stale: bool

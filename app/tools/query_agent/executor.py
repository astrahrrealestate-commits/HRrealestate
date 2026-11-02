"""Safe executor for validated read-only SQL queries under PostgreSQL RLS context."""

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class QueryExecutionResult:
    ok: bool
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    duration_ms: float
    error: str | None = None


def execute_readonly_query(
    engine: Engine,
    company_id: UUID,
    wrapped_sql: str,
) -> QueryExecutionResult:
    """Executes validated SQL inside a read-only transaction with company RLS context.

    Steps:
    1. Opens session.
    2. Runs `SELECT set_config('app.company_id', :cid, true);` to enforce RLS.
    3. Runs the wrapped query under read-only transaction defaults.
    4. Measures execution timing and logs audit record.
    5. Returns structured results.
    """
    start = time.perf_counter()
    try:
        with Session(engine) as session:
            # 1. Enforce per-transaction company isolation for RLS
            session.execute(
                text("SELECT set_config('app.company_id', :cid, true);"),
                {"cid": str(company_id)},
            )

            # 2. Execute the pre-validated query
            cursor = session.execute(text(wrapped_sql))
            cols = list(cursor.keys())
            raw_rows = cursor.fetchall()
            duration_ms = (time.perf_counter() - start) * 1000

            # 3. Format as untrusted data dictionaries
            formatted_rows = [dict(zip(cols, row)) for row in raw_rows]

            log.info(
                "query_agent.executed",
                company_id=str(company_id),
                rows_count=len(formatted_rows),
                duration_ms=round(duration_ms, 2),
                sql=wrapped_sql,
            )

            return QueryExecutionResult(
                ok=True,
                columns=cols,
                rows=formatted_rows,
                row_count=len(formatted_rows),
                duration_ms=duration_ms,
                error=None,
            )
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        log.warning(
            "query_agent.execution_failed",
            company_id=str(company_id),
            error=str(exc),
            duration_ms=round(duration_ms, 2),
            sql=wrapped_sql,
        )
        return QueryExecutionResult(
            ok=False,
            columns=[],
            rows=[],
            row_count=0,
            duration_ms=duration_ms,
            error=str(exc),
        )


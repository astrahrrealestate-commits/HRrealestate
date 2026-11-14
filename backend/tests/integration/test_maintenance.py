"""DBOS system-table retention: terminal workflows older than the cutoff go; recent and running ones stay."""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from dbos import DBOS, SetWorkflowID
from sqlalchemy import Engine

from app.workflows import maintenance

pytestmark = pytest.mark.integration


@DBOS.workflow(name="test.maintenance.noop")
def _noop(tag: str) -> str:
    return tag


def _age(engine: Engine, workflow_id: str, days: int) -> None:
    then = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE dbos.workflow_status SET created_at = :t, updated_at = :t, completed_at = :t "
                "WHERE workflow_uuid = :id"
            ),
            {"t": then, "id": workflow_id},
        )


def _exists(engine: Engine, workflow_id: str) -> bool:
    with engine.connect() as conn:
        query = sa.text("SELECT 1 FROM dbos.workflow_status WHERE workflow_uuid = :id")
        return conn.execute(query, {"id": workflow_id}).first() is not None


def test_retention_deletes_only_old_terminal_workflows(dbos_runtime: None, migrated_engine: Engine) -> None:
    for wid in ("gc:old", "gc:recent"):
        with SetWorkflowID(wid):
            _noop(wid)
    _age(migrated_engine, "gc:old", days=maintenance.RETENTION_DAYS + 5)
    _age(migrated_engine, "gc:recent", days=maintenance.RETENTION_DAYS - 5)

    maintenance.dbos_retention(datetime.now(UTC), None)

    assert not _exists(migrated_engine, "gc:old")
    assert _exists(migrated_engine, "gc:recent")


def test_cutoff_is_derived_from_the_scheduled_time() -> None:
    at = datetime(2026, 10, 8, 4, 45, tzinfo=UTC)
    assert maintenance.cutoff_ms(at) == int((at - timedelta(days=maintenance.RETENTION_DAYS)).timestamp() * 1000)

"""BRIXX sync bookkeeping tables: enums round-trip and one state row per (company, table)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import BrixxRunKind, BrixxRunStatus
from app.db.models import Company
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState

pytestmark = pytest.mark.integration


def test_table_state_unique_per_company_and_table(db: Session, company: Company) -> None:
    db.add(BrixxSyncTableState(company_id=company.id, table_name="PRG_RELATIE"))
    db.flush()
    db.add(BrixxSyncTableState(company_id=company.id, table_name="PRG_RELATIE"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_table_state_defaults_and_run_link(db: Session, company: Company) -> None:
    run = BrixxSyncRun(company_id=company.id, kind=BrixxRunKind.reconcile, started_at=datetime.now(UTC))
    db.add(run)
    db.flush()
    state = BrixxSyncTableState(company_id=company.id, table_name="PRG_OBJECT", last_run_id=run.id)
    db.add(state)
    db.flush()
    db.refresh(state)
    assert state.last_page == 0
    assert state.row_count == 0
    assert state.drifted is False
    assert state.last_success_upd is None
    assert state.last_error is None
    assert state.last_run_id == run.id


def test_other_company_may_reuse_table_name(db: Session, company: Company) -> None:
    other = Company(name="Other")
    db.add(other)
    db.flush()
    db.add_all(
        [
            BrixxSyncTableState(company_id=company.id, table_name="PRG_RELATIE"),
            BrixxSyncTableState(company_id=other.id, table_name="PRG_RELATIE"),
        ]
    )
    db.flush()


def test_run_round_trips_enum_values(db: Session, company: Company) -> None:
    started = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    run = BrixxSyncRun(company_id=company.id, kind=BrixxRunKind.incremental, started_at=started)
    db.add(run)
    db.flush()
    db.refresh(run)
    assert run.status is BrixxRunStatus.running
    assert run.kind is BrixxRunKind.incremental
    assert run.finished_at is None
    assert run.error is None
    run.status = BrixxRunStatus.failed
    run.error = "boom"
    run.finished_at = started
    db.flush()
    db.expire(run)
    assert run.status is BrixxRunStatus.failed
    assert run.error == "boom"
    assert run.started_at == started

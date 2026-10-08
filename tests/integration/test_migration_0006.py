"""Migration 0006: one open wait per case even when no party is set (NULLS NOT DISTINCT), plus review indexes."""

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import Category, Urgency
from app.db.enums import WaitStatus
from app.db.models import Case, Company, WaitRow

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def _wait(company: Company, case: Case, about: str) -> WaitRow:
    return WaitRow(company_id=company.id, case_id=case.id, party_person_id=None, about=about, expected_by=NOW)


def test_one_open_partyless_wait_per_case(db: Session, company: Company) -> None:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal)
    db.add(case)
    db.flush()
    first = _wait(company, case, "photos")
    db.add(first)
    db.flush()
    nested = db.begin_nested()
    db.add(_wait(company, case, "photos again"))
    with pytest.raises(IntegrityError):
        db.flush()
    nested.rollback()
    first.status = WaitStatus.received
    db.flush()
    db.add(_wait(company, case, "new question"))
    db.flush()  # the earlier wait is closed, so a new open one is allowed


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("waits", "ix_waits_source_action_id"),
        ("documents", "ix_documents_model_call_id"),
        ("messages", "ix_messages_pipeline_status_messages_pipeline_attempts"),
    ],
)
def test_review_indexes_exist(db: Session, table: str, index: str) -> None:
    found = db.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE tablename = :t AND indexname = :i"), {"t": table, "i": index}
    ).first()
    assert found is not None

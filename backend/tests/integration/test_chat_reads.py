"""`chat_reads`: one read marker per (company, chat); companies are independent."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import ChatRead, Company

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_chat_key_unique_per_company(db: Session, company: Company) -> None:
    db.add(ChatRead(company_id=company.id, chat_key="person:abc", last_read_at=NOW))
    db.flush()
    db.add(ChatRead(company_id=company.id, chat_key="person:abc", last_read_at=NOW))
    with pytest.raises(IntegrityError):
        db.flush()


def test_other_company_may_reuse_chat_key(db: Session, company: Company) -> None:
    other = Company(name="Other")
    db.add(other)
    db.flush()
    db.add_all(
        [
            ChatRead(company_id=company.id, chat_key="person:abc", last_read_at=NOW),
            ChatRead(company_id=other.id, chat_key="person:abc", last_read_at=NOW),
        ]
    )
    db.flush()

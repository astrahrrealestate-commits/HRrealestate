"""owner_by_email SQL: the one lookup without a company filter (it decides the company)."""

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import owner_by_email
from app.db.models import Company, OwnerAccount

pytestmark = pytest.mark.integration


def _owner(company: Company, phone: str, email: str | None) -> OwnerAccount:
    return OwnerAccount(company_id=company.id, display_name="H", whatsapp_e164=phone, email=email)


def test_single_match_case_insensitive(db: Session, company: Company) -> None:
    owner = _owner(company, "+31611111111", "Harjot@Example.com")
    db.add(owner)
    db.flush()
    principal = owner_by_email(db.connection(), "harjot@EXAMPLE.com")
    assert principal is not None
    assert (principal.company_id, principal.owner_id) == (company.id, owner.id)


def test_no_match_returns_none(db: Session, company: Company) -> None:
    db.add(_owner(company, "+31611111112", "a@example.com"))
    db.flush()
    assert owner_by_email(db.connection(), "other@example.com") is None


def test_null_email_never_matches(db: Session, company: Company) -> None:
    db.add(_owner(company, "+31611111113", None))
    db.flush()
    assert owner_by_email(db.connection(), "") is None


def test_ambiguous_email_returns_none(db: Session, company: Company) -> None:
    second = Company(name="Other")
    db.add(second)
    db.flush()
    db.add_all([_owner(company, "+31611111114", "dup@example.com"), _owner(second, "+31611111115", "DUP@example.com")])
    db.flush()
    assert owner_by_email(db.connection(), "dup@example.com") is None


def test_accepts_engine(migrated_engine: Engine) -> None:
    assert owner_by_email(migrated_engine, "nobody-at-all@example.invalid") is None

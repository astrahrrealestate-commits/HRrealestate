"""Migration 0022 (quote checker): round trip, the snapshot unique key, the new feed kind."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401  (registers tables)
from app.contracts import ActionType, Category, Urgency
from app.contracts.finance import PriceBasis
from app.core.ids import new_id
from app.db.enums import FeedKind
from app.db.models import ActionRow, Case, Company, OwnerFeed, PriceSnapshot
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration
FINANCE_TABLES = {"vendor_rates", "price_snapshots", "quotes", "quote_lines", "quote_reviews"}


@pytest.fixture
def scratch_db_url(pg_url: str) -> Iterator[str]:
    """A separate database on the session container, so a failed round trip cannot break other tests."""
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0022"))
        conn.execute(text("CREATE DATABASE roundtrip_0022"))
    yield make_url(pg_url).set(database="roundtrip_0022").render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0022 WITH (FORCE)"))
    admin.dispose()


def _insert_feed_row(engine: Engine, company_id: UUID, kind: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO owner_feed (id, company_id, idempotency_key, kind, payload) "
                "VALUES (gen_random_uuid(), :company_id, :key, :kind, '{}'::jsonb)"
            ),
            {"company_id": company_id, "key": f"mig0022:{new_id()}", "kind": kind},
        )


def test_0022_round_trip(scratch_db_url: str) -> None:
    """Drift and the full round trip are covered by test_migrations.py; this pins what 0022 itself adds and removes."""
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    company_id = new_id()
    try:
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) >= FINANCE_TABLES
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO companies (id, name) VALUES (:id, 'Round Trip BV')"), {"id": company_id})
        _insert_feed_row(engine, company_id, "quote_review")
        command.downgrade(cfg, "0021")
        assert not FINANCE_TABLES & set(inspect(engine).get_table_names())
        with pytest.raises(IntegrityError):
            _insert_feed_row(engine, company_id, "quote_review")
        _insert_feed_row(engine, company_id, "memory_review")  # the older kinds still pass
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) >= FINANCE_TABLES
    finally:
        engine.dispose()


def _snapshot(company: Company, action: ActionRow, item_key: str) -> PriceSnapshot:
    return PriceSnapshot(
        company_id=company.id,
        case_id=action.case_id,
        action_id=action.id,
        item_key=item_key,
        unit="m2",
        as_of=date(2026, 10, 31),
        low=Decimal("10.00"),
        avg=Decimal("12.00"),
        high=Decimal("15.00"),
        sample_count=3,
        basis=PriceBasis.fake,
    )


def _action(db: Session, company: Company) -> ActionRow:
    case = Case(company_id=company.id, category=Category.maintenance, urgency=Urgency.normal)
    db.add(case)
    db.flush()
    action = ActionRow(
        company_id=company.id,
        case_id=case.id,
        type=ActionType.notify_owner,
        payload={"kind": "notify_owner", "text": "x"},
        rationale="r",
        context_ref=[],
    )
    db.add(action)
    db.flush()
    return action


def test_snapshot_unique_per_action_item(db: Session, company: Company) -> None:
    action = _action(db, company)
    db.add(_snapshot(company, action, "painting"))
    db.add(_snapshot(company, action, "plumbing"))  # another item on the same decision is fine
    db.flush()
    db.add(_snapshot(company, action, "painting"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_feed_kind_accepts_quote_review(db: Session, company: Company) -> None:
    db.add(
        OwnerFeed(
            company_id=company.id,
            idempotency_key=f"quote:{new_id()}",
            kind=FeedKind.quote_review,
            payload={},
        )
    )
    db.flush()

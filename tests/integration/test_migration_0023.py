"""Migration 0023 (due diligence lite): round trip, the new feed kind and the once-per-document read."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401  (registers tables)
from app.core.ids import new_id
from app.db.enums import FeedKind
from app.db.models import Company, DDDocumentRead, OwnerFeed
from tests.integration.conftest import alembic_config
from tests.integration.diligence_support import make_document

pytestmark = pytest.mark.integration
DD_TABLES = {"dd_reviews", "dd_review_documents", "dd_document_reads"}


@pytest.fixture
def scratch_db_url(pg_url: str) -> Iterator[str]:
    """A separate database on the session container, so a failed round trip cannot break other tests."""
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0023"))
        conn.execute(text("CREATE DATABASE roundtrip_0023"))
    yield make_url(pg_url).set(database="roundtrip_0023").render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0023 WITH (FORCE)"))
    admin.dispose()


def _insert_feed_row(engine: Engine, company_id: UUID, kind: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO owner_feed (id, company_id, idempotency_key, kind, payload) "
                "VALUES (gen_random_uuid(), :company_id, :key, :kind, '{}'::jsonb)"
            ),
            {"company_id": company_id, "key": f"mig0023:{new_id()}", "kind": kind},
        )


def test_0023_round_trip(scratch_db_url: str) -> None:
    """Drift and the full round trip are covered by test_migrations.py; this pins what 0023 itself adds and removes."""
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    company_id = new_id()
    try:
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) >= DD_TABLES
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO companies (id, name) VALUES (:id, 'Round Trip BV')"), {"id": company_id})
        _insert_feed_row(engine, company_id, "dd_report")
        command.downgrade(cfg, "0022")
        assert not DD_TABLES & set(inspect(engine).get_table_names())
        with pytest.raises(IntegrityError):
            _insert_feed_row(engine, company_id, "dd_report")
        _insert_feed_row(engine, company_id, "memory_review")  # the older kinds still pass
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) >= DD_TABLES
    finally:
        engine.dispose()


def test_feed_kind_accepts_dd_report(db: Session, company: Company) -> None:
    db.add(OwnerFeed(company_id=company.id, idempotency_key=f"dd:{new_id()}", kind=FeedKind.dd_report, payload={}))
    db.flush()


def test_one_read_per_document_and_reader_version(db: Session, company: Company) -> None:
    doc_id = make_document(db, company.id, "Verkoopbrochure")
    db.add(DDDocumentRead(company_id=company.id, document_id=doc_id, reader_version="dd_reader/v1", read={}))
    db.add(DDDocumentRead(company_id=company.id, document_id=doc_id, reader_version="dd_reader/v2", read={}))
    db.flush()  # a new reader version is a new read
    db.add(DDDocumentRead(company_id=company.id, document_id=doc_id, reader_version="dd_reader/v1", read={}))
    with pytest.raises(IntegrityError):
        db.flush()

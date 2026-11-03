"""Migration 0030 (backend hardening): case-insensitive Gmail mailbox uniqueness, lookup indexes, pipeline_done_at."""

from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.db.models  # noqa: F401  (registers tables)
from app.contracts import Channel
from app.core.ids import new_id
from app.db.models import ChannelAccount, Company
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration
NEW_INDEXES = {
    ("channel_accounts", "uq_channel_accounts_gmail_address_lower"),
    ("drive_reorg_items", "ix_drive_reorg_items_document_id"),
    ("dd_reviews", "ix_dd_reviews_unit_id"),
}


@pytest.fixture
def scratch_db_url(pg_url: str) -> Iterator[str]:
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0030"))
        conn.execute(text("CREATE DATABASE roundtrip_0030"))
    yield make_url(pg_url).set(database="roundtrip_0030").render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text("DROP DATABASE IF EXISTS roundtrip_0030 WITH (FORCE)"))
    admin.dispose()


def _indexes(engine: Engine) -> set[tuple[str, str]]:
    insp = inspect(engine)
    return {(t, i["name"]) for t, _ in NEW_INDEXES for i in insp.get_indexes(t) if i["name"]}


def _add_mailbox(engine: Engine, company_id: object, address: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO channel_accounts (id, company_id, channel, address) VALUES (:id, :c, 'gmail', :a)"),
            {"id": new_id(), "c": company_id, "a": address},
        )


def test_0030_round_trip(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    try:
        command.upgrade(cfg, "head")
        assert _indexes(engine) >= NEW_INDEXES
        assert "pipeline_done_at" in {c["name"] for c in inspect(engine).get_columns("messages")}
        command.downgrade(cfg, "0029")
        assert not _indexes(engine) & NEW_INDEXES
        assert "pipeline_done_at" not in {c["name"] for c in inspect(engine).get_columns("messages")}
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_0030_refuses_case_duplicate_mailboxes_with_a_clear_error(scratch_db_url: str) -> None:
    cfg = alembic_config(scratch_db_url)
    engine = create_engine(scratch_db_url)
    company_id = new_id()
    try:
        command.upgrade(cfg, "0029")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO companies (id, name) VALUES (:id, 'Dup BV')"), {"id": company_id})
        _add_mailbox(engine, company_id, "Harjot@Example.test")
        _add_mailbox(engine, company_id, "harjot@example.test")
        with pytest.raises(RuntimeError, match="differ only in case"):
            command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_gmail_address_is_unique_whatever_its_case(db: Session, company: Company) -> None:
    db.add(ChannelAccount(company_id=company.id, channel=Channel.gmail, address=f"Box-{company.id}@example.test"))
    db.flush()
    db.add(ChannelAccount(company_id=company.id, channel=Channel.gmail, address=f"box-{company.id}@EXAMPLE.test"))
    with pytest.raises(IntegrityError):
        db.flush()

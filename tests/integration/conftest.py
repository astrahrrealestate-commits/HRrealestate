"""Integration fixtures: one throwaway Postgres 16 per test session (testcontainers), real Alembic migrations."""

import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from testcontainers.community.postgres import PostgresContainer

if TYPE_CHECKING:
    from uuid import UUID

    from dbos import DBOSClient

from app.core.settings import Settings
from app.db.models import Company
from app.db.session import make_engine

ROOT = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "app" / "db" / "alembic"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """Also exported as DATABASE_URL, so code reading `get_settings()` (workflow steps) uses the test database and
    never a developer `.env`."""
    from app.core.settings import get_settings

    with PostgresContainer("pgvector/pgvector:0.8.2-pg16", driver="psycopg") as pg:
        url = pg.get_connection_url()
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        yield url
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_engine(pg_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(pg_url), "head")
    engine = make_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is always rolled back: tests never see each other's rows."""
    with migrated_engine.connect() as conn:
        outer = conn.begin()
        session = Session(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


@pytest.fixture
def company(db: Session) -> Company:
    c = Company(name="Test Hausverwaltung")
    db.add(c)
    db.flush()
    return c


@pytest.fixture(scope="session")
def test_settings(pg_url: str) -> Settings:
    return Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def dbos_runtime(test_settings: Settings, migrated_engine: Engine) -> Iterator[None]:
    """Fresh DBOS executor per test against the session Postgres (schema `dbos`), per DBOS testing guidance."""
    from dbos import DBOS

    from app.workflows.deps import set_engine
    from app.workflows.runtime import launch

    DBOS.destroy()
    launch(test_settings, reset_for_tests=True)
    set_engine(migrated_engine)  # workflow steps use the test database, never DATABASE_URL from .env
    yield
    set_engine(None)
    DBOS.destroy()


@pytest.fixture
def dbos_tables(test_settings: Settings, migrated_engine: Engine) -> None:
    """DBOS system tables exist and are empty, but no executor runs (enqueued work just waits).

    Request it BEFORE `db`: resetting the system database terminates other open connections.
    """
    from dbos import DBOS

    from app.workflows.runtime import launch

    DBOS.destroy()
    launch(test_settings, reset_for_tests=True, schedules=False)
    DBOS.destroy()


@pytest.fixture
def dbos_client(test_settings: Settings, dbos_tables: None) -> Iterator["DBOSClient"]:

    from dbos import DBOSClient

    client = DBOSClient(system_database_url=test_settings.dbos_database_url)
    yield client
    client.destroy()


@pytest.fixture
def committed_company(migrated_engine: Engine) -> Iterator[Company]:
    """A committed company for tests that exercise code opening its own sessions; everything is deleted after."""
    with Session(migrated_engine, expire_on_commit=False) as session:
        company = Company(name="Committed GmbH")
        session.add(company)
        session.commit()
    yield company
    _stop_background_work()
    purge_company(migrated_engine, company.id)


def _stop_background_work() -> None:
    """Workflows a test started (process_event → pipeline_entry → …) may still be writing this company's rows; a
    purge racing them hits FK violations and leaves rows that break the next test's setup. Stop the executor first
    and let in-flight workflows finish (idempotent: fixtures destroy DBOS again in their own teardown)."""
    from dbos import DBOS

    DBOS.destroy(workflow_completion_timeout_sec=15)


def purge_company(engine: Engine, company_id: "UUID") -> None:
    """Delete a committed company and every company-scoped row, children first (FK order)."""
    from sqlalchemy import delete
    from sqlalchemy.exc import IntegrityError

    import app.db.models  # noqa: F401  (registers every table)
    from app.db.base import Base

    for attempt in range(3):  # a straggling write can still land between deletes: retry the whole purge
        try:
            with Session(engine) as session:
                for table in reversed(Base.metadata.sorted_tables):
                    if "company_id" in table.c:
                        session.execute(delete(table).where(table.c.company_id == company_id))
                session.execute(delete(Company).where(Company.id == company_id))
                session.commit()
            return
        except IntegrityError:
            if attempt == 2:
                raise
            time.sleep(1)

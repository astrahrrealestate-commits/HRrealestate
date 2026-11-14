"""BRIXX status API against real Postgres: seeded table states, company scoping, session auth, the stale window."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.core.settings import Settings
from app.db.enums import BrixxRunKind, BrixxRunStatus
from app.db.models import Company, OwnerAccount
from app.db.models.brixx import BrixxSyncRun, BrixxSyncTableState
from app.main import create_app
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
URL = "/api/v1/brixx/status"
INTERVAL = 15


@dataclass
class Fx:
    client: TestClient
    engine: Engine
    company_id: UUID
    other_id: UUID


def _run(s: Session, company_id: UUID, *, age: timedelta, status: BrixxRunStatus) -> BrixxSyncRun:
    started = datetime.now(UTC) - age
    finished = None if status is BrixxRunStatus.running else started + timedelta(minutes=1)
    run = BrixxSyncRun(
        company_id=company_id, kind=BrixxRunKind.incremental, status=status, started_at=started, finished_at=finished
    )
    s.add(run)
    s.flush()
    return run


def _state(s: Session, company_id: UUID, name: str, run: BrixxSyncRun | None, **values: object) -> None:
    run_id = None if run is None else run.id
    s.add(BrixxSyncTableState(company_id=company_id, table_name=name, last_run_id=run_id, **values))
    s.flush()


@pytest.fixture
def fx(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Fx]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999994",
                             email="h@b.test")  # fmt: skip
        s.add(owner)
        s.commit()
    settings = Settings(database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32),  # type: ignore[arg-type]
                        brixx_sync_interval_minutes=INTERVAL, _env_file=None)  # fmt: skip
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@b.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield Fx(c, migrated_engine, committed_company.id, other.id)
    purge_company(migrated_engine, other.id)


def test_unauthenticated_is_401(fx: Fx) -> None:
    fx.client.cookies.clear()
    assert fx.client.get(URL).status_code == 401


def test_no_runs_yet_is_empty_and_stale(fx: Fx) -> None:
    body = fx.client.get(URL).json()
    assert body == {"last_run": None, "tables": [], "total_rows": 0, "stale": True}


def test_returns_seeded_table_states_and_the_newest_run(fx: Fx) -> None:
    watermark = datetime(2026, 10, 31, 8, 0, tzinfo=UTC)
    with Session(fx.engine) as s:
        done = _run(s, fx.company_id, age=timedelta(minutes=20), status=BrixxRunStatus.succeeded)
        newest = _run(s, fx.company_id, age=timedelta(minutes=2), status=BrixxRunStatus.running)
        _state(s, fx.company_id, "PRG_RELATIE", done, row_count=40, last_success_upd=watermark)
        _state(s, fx.company_id, "PRG_OBJECT", newest, row_count=5, last_page=2, last_success_upd=watermark,
               drifted=True)  # fmt: skip
        auth_error = "BrixxAuthError table=PRG_CONTRACT page=2"
        _state(s, fx.company_id, "PRG_CONTRACT", newest, last_page=1, last_error=auth_error)
        done_started, newest_id = done.started_at, newest.id
        s.commit()
    body = fx.client.get(URL).json()
    assert body["last_run"]["id"] == str(newest_id)
    assert (body["last_run"]["status"], body["last_run"]["kind"]) == ("running", "incremental")
    tables = {t["name"]: t for t in body["tables"]}
    assert [t["name"] for t in body["tables"]] == ["PRG_CONTRACT", "PRG_OBJECT", "PRG_RELATIE"]
    assert body["total_rows"] == 45
    relatie = tables["PRG_RELATIE"]
    assert datetime.fromisoformat(relatie["last_success_at"]) == done_started  # finished clean in its last run
    assert 19 * 60 <= relatie["lag_seconds"] <= 21 * 60
    assert datetime.fromisoformat(tables["PRG_OBJECT"]["last_success_at"]) == watermark  # mid-run: the watermark
    assert tables["PRG_OBJECT"]["drifted"] is True
    assert tables["PRG_CONTRACT"]["last_error"] == "BrixxAuthError table=PRG_CONTRACT page=2"
    assert tables["PRG_CONTRACT"]["last_success_at"] is None
    assert body["stale"] is False  # `done` finished 19 minutes ago, inside 3 x 15


def test_other_companys_states_and_runs_never_appear(fx: Fx) -> None:
    with Session(fx.engine) as s:
        theirs = _run(s, fx.other_id, age=timedelta(minutes=1), status=BrixxRunStatus.succeeded)
        _state(s, fx.other_id, "PRG_SECRET", theirs, row_count=99)
        mine = _run(s, fx.company_id, age=timedelta(hours=3), status=BrixxRunStatus.failed)
        _state(s, fx.other_id, "PRG_RELATIE", theirs, row_count=7)
        _state(s, fx.company_id, "PRG_RELATIE", mine, row_count=1, last_error="BrixxError table=PRG_RELATIE page=1")
        mine_id = mine.id
        s.commit()
    body = fx.client.get(URL).json()
    assert [t["name"] for t in body["tables"]] == ["PRG_RELATIE"]
    assert body["tables"][0]["row_count"] == 1
    assert body["total_rows"] == 1
    assert body["last_run"]["id"] == str(mine_id)  # their newer run is not ours
    assert body["stale"] is True  # their fresh success does not make ours fresh


def test_stale_when_the_last_success_is_older_than_the_window(fx: Fx) -> None:
    with Session(fx.engine) as s:
        _run(s, fx.company_id, age=timedelta(minutes=3 * INTERVAL + 5), status=BrixxRunStatus.succeeded)
        _run(s, fx.company_id, age=timedelta(minutes=5), status=BrixxRunStatus.failed)  # recent but failed
        s.commit()
    body = fx.client.get(URL).json()
    assert body["last_run"]["status"] == "failed"
    assert body["stale"] is True

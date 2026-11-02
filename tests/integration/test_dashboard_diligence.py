"""Due diligence API against real Postgres: scoped, CSRF-guarded, queued after the row is saved, report sanitised."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.core.settings import Settings
from app.db.models import Company, OwnerAccount
from app.diligence import service
from app.diligence.framework import default_framework
from app.main import create_app
from tests.integration.conftest import purge_company
from tests.integration.diligence_support import make_document

pytestmark = pytest.mark.integration
CSRF = {CSRF_HEADER: CSRF_VALUE}
BROCHURE = "Verkoopbrochure Kerkstraat 12\nBouwjaar: 1985\nAdres: Kerkstraat 12 https://evil.example/x"
DEED = "Akte van levering\nBouwjaar: 1965"


@dataclass
class Fixture:
    client: TestClient
    engine: Engine
    settings: Settings
    company_id: UUID
    mine: list[UUID]
    theirs: UUID
    workflow: MagicMock


@pytest.fixture
def fx(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Fixture]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.flush()
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999993",
                             email="h@a.test")  # fmt: skip
        s.add(owner)
        s.flush()
        mine = [make_document(s, committed_company.id, BROCHURE), make_document(s, committed_company.id, DEED)]
        theirs = make_document(s, other.id, "Verkoopbrochure Eve")
        s.commit()
    settings = Settings(database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32),  # type: ignore[arg-type]
                        _env_file=None)  # fmt: skip
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    workflow = MagicMock()
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=workflow)) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield Fixture(c, migrated_engine, settings, committed_company.id, mine, theirs, workflow)
    purge_company(migrated_engine, other.id)


def _start(fx: Fixture, **over: object) -> dict[str, object]:
    body = {"title": "Kerkstraat 12", "property_kind": "house", "document_ids": [str(d) for d in fx.mine], **over}
    resp = fx.client.post("/api/v1/diligence/reviews", json=body, headers=CSRF)
    assert resp.status_code == 202, resp.text
    return resp.json()  # type: ignore[no-any-return]


def _finish(fx: Fixture, review_id: str, run_no: int = 1) -> None:
    rid = UUID(review_id)
    ids = service.begin_run(fx.engine, fx.company_id, rid, run_no)
    assert ids is not None
    for d in ids:
        service.read_document(fx.engine, fx.settings, fx.company_id, d)
    service.compile_review(fx.engine, default_framework(), fx.company_id, rid, run_no, date(2026, 10, 31))


def test_requires_a_session_and_csrf(fx: Fixture) -> None:
    body = {"title": "t", "property_kind": "house", "document_ids": [str(fx.mine[0])]}
    assert fx.client.post("/api/v1/diligence/reviews", json=body).status_code == 403  # no CSRF header
    fx.client.cookies.clear()
    assert fx.client.get("/api/v1/diligence/reviews").status_code == 401
    assert fx.client.post("/api/v1/diligence/reviews", json=body, headers=CSRF).status_code == 401


def test_start_saves_the_row_then_queues_one_run(fx: Fixture) -> None:
    created = _start(fx)
    assert created["run_no"] == 1
    assert fx.workflow.enqueue.call_count == 1
    options, *args = fx.workflow.enqueue.call_args.args
    assert options["workflow_id"] == f"dd:{created['id']}:1"
    assert args == [str(fx.company_id), created["id"], 1]
    detail = fx.client.get(f"/api/v1/diligence/reviews/{created['id']}").json()
    assert (detail["status"], detail["report"], detail["document_ids"]) == ("pending", None, [str(d) for d in fx.mine])


def test_start_rejects_foreign_and_missing_documents_and_empty_sets(fx: Fixture) -> None:
    for ids in ([str(fx.theirs)], [str(fx.mine[0]), str(uuid4())]):
        resp = fx.client.post(
            "/api/v1/diligence/reviews",
            json={"title": "t", "property_kind": "house", "document_ids": ids},
            headers=CSRF,
        )
        assert resp.status_code == 404
    empty = {"title": "t", "property_kind": "house", "document_ids": []}
    assert fx.client.post("/api/v1/diligence/reviews", json=empty, headers=CSRF).status_code == 422
    assert fx.workflow.enqueue.call_count == 0


def test_report_is_served_with_links_stripped(fx: Fixture) -> None:
    created = _start(fx)
    _finish(fx, str(created["id"]))
    detail = fx.client.get(f"/api/v1/diligence/reviews/{created['id']}").json()
    assert (detail["status"], detail["verdict"]) == ("done", "red_flags")
    report = detail["report"]
    assert [m["field"] for m in report["mismatches"]] == ["year_built"]
    assert "evil.example" not in str(report)
    assert report["disclaimer"]


def test_list_and_read_are_company_scoped(fx: Fixture, migrated_engine: Engine) -> None:
    created = _start(fx)
    assert [r["id"] for r in fx.client.get("/api/v1/diligence/reviews").json()] == [created["id"]]
    assert fx.client.get(f"/api/v1/diligence/reviews/{uuid4()}").status_code == 404


def test_rerun_bumps_the_run_and_queues_it(fx: Fixture) -> None:
    created = _start(fx)
    resp = fx.client.post(f"/api/v1/diligence/reviews/{created['id']}/rerun", json={}, headers=CSRF)
    assert (resp.status_code, resp.json()["run_no"]) == (202, 2)
    assert fx.workflow.enqueue.call_args.args[0]["workflow_id"] == f"dd:{created['id']}:2"
    swap = {"document_ids": [str(fx.mine[1])]}
    again = fx.client.post(f"/api/v1/diligence/reviews/{created['id']}/rerun", json=swap, headers=CSRF)
    assert again.json()["run_no"] == 3
    assert fx.client.get(f"/api/v1/diligence/reviews/{created['id']}").json()["document_ids"] == [str(fx.mine[1])]


def test_rerun_is_refused_while_running_and_for_unknown_reviews(fx: Fixture) -> None:
    created = _start(fx)
    service.begin_run(fx.engine, fx.company_id, UUID(str(created["id"])), 1)
    busy = fx.client.post(f"/api/v1/diligence/reviews/{created['id']}/rerun", json={}, headers=CSRF)
    assert busy.status_code == 409
    missing = fx.client.post(f"/api/v1/diligence/reviews/{uuid4()}/rerun", json={}, headers=CSRF)
    assert missing.status_code == 404

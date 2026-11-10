"""Calendar routes act only on the signed-in owner's company; approving an event pushes it to Google exactly once."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.contracts import Category, Urgency
from app.core.settings import Settings
from app.db.models import Case, CaseEvent, Company
from app.db.models.calendar import CalendarEventRow
from app.main import create_app
from tests.api_auth import as_owner

pytestmark = pytest.mark.integration
START = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)


@dataclass
class Cal:
    client: TestClient
    engine: Engine
    gcal: MagicMock
    mine_case: UUID
    their_case: UUID
    their_event: UUID
    my_company: UUID
    their_company: UUID


def _event(s: Session, company_id: UUID, case_id: UUID | None, status: str = "proposed") -> UUID:
    row = CalendarEventRow(
        company_id=company_id, case_id=case_id, title="Boiler visit", start_time=START,
        end_time=START + timedelta(hours=1), status=status, attendees=[{"email": "tech@example.test"}],
    )  # fmt: skip
    s.add(row)
    s.flush()
    return row.id


@pytest.fixture
def cal(migrated_engine: Engine, pg_url: str) -> Iterator[Cal]:
    with Session(migrated_engine) as s:
        mine, theirs = Company(name="Cal A"), Company(name="Cal B")
        s.add_all([mine, theirs])
        s.flush()
        ids = (mine.id, theirs.id)
        my_case = Case(company_id=ids[0], category=Category.maintenance, urgency=Urgency.low, summary="a")
        their_case = Case(company_id=ids[1], category=Category.maintenance, urgency=Urgency.low, summary="b")
        s.add_all([my_case, their_case])
        s.flush()
        case_ids = (my_case.id, their_case.id)
        their_event = _event(s, ids[1], case_ids[1])
        _event(s, ids[0], case_ids[0])
        s.commit()
    gcal = MagicMock()
    gcal.create_event.return_value = SimpleNamespace(id="g-1", html_link="https://calendar.example/g-1")
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=ids[0], owner_id=uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=migrated_engine, workflow_client=MagicMock()), owner)
    with patch("app.api.calendar.routes.get_calendar_client", return_value=gcal), TestClient(app) as client:
        yield Cal(client, migrated_engine, gcal, case_ids[0], case_ids[1], their_event, ids[0], ids[1])
    with Session(migrated_engine) as s:
        for company_id in ids:
            for model in (CalendarEventRow, CaseEvent, Case):
                s.query(model).filter(model.company_id == company_id).delete(synchronize_session=False)
            s.query(Company).filter(Company.id == company_id).delete()
        s.commit()


def _payload(**extra: object) -> dict[str, object]:
    return {
        "title": "Visit",
        "startTime": START.isoformat(),
        "endTime": (START + timedelta(hours=1)).isoformat(),
        **extra,
    }


def _count(cal: Cal, company_id: UUID) -> int:
    with Session(cal.engine) as s:
        return (
            s.scalar(
                select(func.count()).select_from(CalendarEventRow).where(CalendarEventRow.company_id == company_id)
            )
            or 0
        )


def test_the_list_shows_only_the_owners_events(cal: Cal) -> None:
    body = cal.client.get("/api/calendar/events").json()
    assert body["total"] == 1
    assert str(cal.their_event) not in str(body)


def test_an_event_cannot_be_attached_to_another_companys_case(cal: Cal) -> None:
    r = cal.client.post("/api/calendar/events", json=_payload(caseId=str(cal.their_case)))
    assert r.status_code == 404
    assert _count(cal, cal.my_company) == 1  # nothing was created


def test_a_new_event_belongs_to_the_signed_in_company(cal: Cal) -> None:
    r = cal.client.post("/api/calendar/events", json=_payload(caseId=str(cal.mine_case), contractorEmail="x@y.test"))
    assert r.status_code == 200
    assert _count(cal, cal.my_company) == 2
    assert _count(cal, cal.their_company) == 1


def test_a_malformed_id_is_a_422_not_a_server_error(cal: Cal) -> None:
    assert cal.client.post("/api/calendar/events", json=_payload(caseId="not-a-uuid")).status_code == 422


def test_another_companys_event_cannot_be_approved_or_pushed(cal: Cal) -> None:
    r = cal.client.post(f"/api/calendar/events/{cal.their_event}/approve")
    assert r.status_code == 404
    cal.gcal.create_event.assert_not_called()


def test_approving_twice_pushes_to_google_once(cal: Cal) -> None:
    created = cal.client.post("/api/calendar/events", json=_payload(caseId=str(cal.mine_case))).json()
    first = cal.client.post(f"/api/calendar/events/{created['id']}/approve")
    second = cal.client.post(f"/api/calendar/events/{created['id']}/approve")
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["externalEventId"] == second.json()["externalEventId"] == "g-1"
    assert cal.gcal.create_event.call_count == 1
    with Session(cal.engine) as s:
        case = s.get(Case, cal.mine_case)
        assert case is not None
        assert "Visit scheduled on Google Calendar" in (case.summary or "")
        notes = s.scalars(select(CaseEvent.note).where(CaseEvent.case_id == cal.mine_case)).all()
    assert len(notes) == 1  # the second click added no second event
    assert "Google Event ID: g-1" in (notes[0] or "")


def test_a_cancelled_event_cannot_be_approved(cal: Cal) -> None:
    with Session(cal.engine) as s:
        cancelled = _event(s, cal.my_company, None, status="cancelled")
        s.commit()
    assert cal.client.post(f"/api/calendar/events/{cancelled}/approve").status_code == 409
    cal.gcal.create_event.assert_not_called()

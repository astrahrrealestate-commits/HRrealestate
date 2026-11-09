"""Unit and integration tests for the EstateOS Calendar Agent.

Verifies:
1. Natural language time & slot extraction (English & Dutch).
2. Lockbox requirement detection.
3. Fallback when message has no time expressions.
4. FakeCalendarClient CRUD, free/busy, and conflict handling with fake credentials.
5. Conflict resolution & alternative slot proposal.
6. REST API: /api/calendar/propose, /api/calendar/events, and 1-click /api/calendar/events/{id}/approve.
7. Super Agent integration: /api/agent/ask producing type="calendar_item" previewCard with 1-click action.
8. Super Agent listing of scheduled visits.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.channels.calendar import (
    CalendarAttendee,
    CalendarEventCreate,
    FakeCalendarClient,
)
from app.contracts import CaseState, Category, Urgency
from app.core.settings import Settings
from app.db.models import CalendarEventRow, Case, Company, Unit
from app.llm.agents.calendar import (
    detect_lockbox_need,
    extract_time_window,
    propose_calendar_event,
)
from app.main import create_app
from tests.api_auth import as_owner

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    gmail_credentials_file="",
    _env_file=None,
)
TEST_COMP_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(autouse=True)
def force_fake_calendar():
    fake = FakeCalendarClient()
    with (
        patch("app.channels.calendar.get_calendar_client", return_value=fake),
        patch("app.api.calendar.routes.get_calendar_client", return_value=fake),
    ):
        yield fake


# ---------------------------------------------------------------------------
# 1. TIME WINDOW EXTRACTION TESTS
# ---------------------------------------------------------------------------


def test_extract_time_window_range_dutch_and_english():
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)  # Wednesday

    # Dutch range
    tw_nl = extract_time_window("Monteur kan morgen tussen 11:30 en 12:30 komen", reference_date=ref)
    assert tw_nl.start_time.hour == 11
    assert tw_nl.start_time.minute == 30
    assert tw_nl.end_time.hour == 12
    assert tw_nl.end_time.minute == 30
    assert tw_nl.start_time.day == 29
    assert tw_nl.confidence >= 0.90

    # English range
    tw_en = extract_time_window("Kevin will arrive tomorrow between 14:00 - 15:30", reference_date=ref)
    assert tw_en.start_time.hour == 14
    assert tw_en.end_time.hour == 15
    assert tw_en.end_time.minute == 30
    assert tw_en.start_time.day == 29


def test_extract_time_window_specific_hour_and_day():
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)  # Wednesday

    # Friday at 3 PM
    tw = extract_time_window("Schedule inspection for Friday at 3 PM", reference_date=ref)
    assert tw.start_time.weekday() == 4  # Friday
    assert tw.start_time.hour == 15
    assert tw.end_time.hour == 16
    assert tw.confidence >= 0.85

    # Dutch: vrijdag om 15:00
    tw_nl = extract_time_window("Kan Kevin vrijdag om 15:00 langskomen?", reference_date=ref)
    assert tw_nl.start_time.weekday() == 4
    assert tw_nl.start_time.hour == 15


def test_detect_lockbox_need():
    assert detect_lockbox_need("Ik ben niet thuis, gebruik de sleutelkluis") is True
    assert detect_lockbox_need("I am at work, lockbox code is available") is True
    assert detect_lockbox_need("Please fix the leaking pipe in the bathroom") is False


def test_missing_time_graceful_fallback():
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    tw = extract_time_window("There is a leak under the sink, please send someone", reference_date=ref)
    assert tw.is_default_fallback is True
    assert tw.confidence == 0.50
    assert tw.start_time.hour == 10
    assert tw.end_time.hour == 11


# ---------------------------------------------------------------------------
# 2. FAKE CALENDAR CLIENT CRUD & FREE/BUSY TESTS
# ---------------------------------------------------------------------------


def test_fake_calendar_client_lifecycle():
    client = FakeCalendarClient(credentials={"fake": "mock_test_token"})
    now = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)

    # 1. Create event
    created = client.create_event(
        CalendarEventCreate(
            title="Boiler Maintenance",
            start_time=now,
            end_time=now + timedelta(hours=1),
            location="Keizersgracht 42-A",
            attendees=[CalendarAttendee(email="kevin@chahalbouw.nl", display_name="Kevin")],
        )
    )
    assert created.id.startswith("gcal_evt_")
    assert created.status == "confirmed"
    assert "https://calendar.google.com" in created.html_link

    # 2. List events
    events = client.list_events(now - timedelta(days=1), now + timedelta(days=1))
    assert len(events) == 1
    assert events[0].title == "Boiler Maintenance"

    # 3. Check Free / Busy
    busy = client.check_free_busy(now - timedelta(hours=2), now + timedelta(hours=2))
    assert len(busy) == 1
    assert busy[0].start_time == now

    # 4. Update event
    updated = client.update_event(created.id, {"title": "Boiler Inspection & Filter Replacement"})
    assert updated.title == "Boiler Inspection & Filter Replacement"

    # 5. Delete event
    deleted = client.delete_event(created.id)
    assert deleted is True
    # Should not appear in active listings
    remaining = client.list_events(now - timedelta(days=1), now + timedelta(days=1))
    assert len(remaining) == 0


def test_conflict_detection_and_alternative_proposal():
    client = FakeCalendarClient()
    friday_3pm = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)

    # Pre-seed a conflicting event on Friday 15:00 - 16:00
    client.seed_event(
        title="Existing Roof Inspection",
        start_time=friday_3pm,
        end_time=friday_3pm + timedelta(hours=1),
        location="Singel 412",
    )

    # Try to propose event at the same time
    proposal = propose_calendar_event(
        message_text="Schedule Kevin for Friday at 3 PM",
        property_address="Keizersgracht 42-A",
        calendar_client=client,
        reference_date=datetime(2026, 10, 28, 9, 0, tzinfo=UTC),
    )

    assert proposal.has_conflict is True
    assert "collides with existing booking" in (proposal.conflict_reason or "").lower()
    assert proposal.alternative_slot is not None
    # Proposed alternative should be after 16:00
    assert proposal.alternative_slot.start_time >= friday_3pm + timedelta(hours=1)


# ---------------------------------------------------------------------------
# 3. CALENDAR REST API ENDPOINTS
# ---------------------------------------------------------------------------


def create_test_mock_session(events_map=None, cases_map=None):
    events_map = events_map or {}
    cases_map = cases_map or {}
    company = Company(id=TEST_COMP_ID, name="EstateOS Test")

    mock_sess = MagicMock()

    def mock_scalars(query):
        result = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            result.first.return_value = company
        elif "from calendar_events" in q_str:
            result.all.return_value = list(events_map.values())
        elif "from cases" in q_str:
            result.all.return_value = list(cases_map.values())
        else:
            result.first.return_value = None
            result.all.return_value = []
        return result

    def mock_get(model, ident):
        if model == CalendarEventRow:
            return events_map.get(ident)
        if model == Case:
            return cases_map.get(ident)
        if model == Company:
            return company
        return None

    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = mock_get
    mock_sess.__enter__.return_value = mock_sess
    return mock_sess


def test_calendar_api_propose_endpoint():
    mock_engine = MagicMock()
    mock_wf = MagicMock()
    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))

    with TestClient(app) as client:
        res = client.post(
            "/api/calendar/propose",
            json={
                "messageText": "Monteur kan morgen tussen 11:30 en 12:30 langskomen. Gebruik sleutelkluis.",
                "propertyAddress": "Keizersgracht 42-A",
                "contractorName": "Kevin van Dijk (Technician)",
                "contractorEmail": "kevin@chahalbouw.nl",
                "lockboxCode": "4182",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert "Keizersgracht 42-A" in data["location"]
        assert data["lockboxCode"] == "4182"
        assert data["requiresLockbox"] is True
        assert data["hasConflict"] is False


def test_calendar_api_1click_approve():
    evt_id = uuid4()
    case_id = uuid4()
    start_time = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)
    end_time = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)

    mock_event = CalendarEventRow(
        id=evt_id,
        company_id=TEST_COMP_ID,
        case_id=case_id,
        title="Plumbing Repair · Keizersgracht 42-A",
        description="Leaking pipe repair",
        start_time=start_time,
        end_time=end_time,
        location="Keizersgracht 42-A",
        status="proposed",
        event_type="contractor_repair",
        attendees=[{"email": "kevin@chahalbouw.nl", "displayName": "Kevin"}],
        lockbox_code="4182",
    )
    mock_case = Case(
        id=case_id,
        company_id=TEST_COMP_ID,
        category=Category.maintenance,
        urgency=Urgency.emergency,
        state=CaseState.waiting_on_third_party,
        summary="Active leak ticket.",
    )

    mock_sess = create_test_mock_session(
        events_map={evt_id: mock_event},
        cases_map={case_id: mock_case},
    )
    mock_engine = MagicMock()
    mock_wf = MagicMock()

    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))

    with (
        patch("app.api.calendar.routes.Session", return_value=mock_sess),
        TestClient(app) as client,
    ):
        res = client.post(f"/api/calendar/events/{evt_id}/approve")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "confirmed"
        assert data["externalEventId"] is not None
        assert "calendar.google.com" in data["htmlLink"]

        # Verify case summary was updated
        assert "Calendar Scheduled" in mock_case.summary
        assert "Visit scheduled on Google Calendar" in mock_case.summary


# ---------------------------------------------------------------------------
# 4. SUPER AGENT INTEGRATION TESTS
# ---------------------------------------------------------------------------


def test_super_agent_schedule_command_returns_preview_card():
    case_id = uuid4()
    unit_id = uuid4()
    mock_unit = Unit(id=unit_id, company_id=TEST_COMP_ID, address="Keizersgracht 42-A")
    mock_case = Case(
        id=case_id,
        company_id=TEST_COMP_ID,
        unit_id=unit_id,
        category=Category.maintenance,
        urgency=Urgency.emergency,
        state=CaseState.waiting_on_third_party,
        summary="Emergency water pipe leakage.",
    )

    company = Company(id=TEST_COMP_ID, name="EstateOS Test")
    mock_sess = MagicMock()

    def mock_scalars(query):
        result = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            result.first.return_value = company
        elif "from cases" in q_str:
            result.all.return_value = [mock_case]
            result.first.return_value = mock_case
        elif "from calendar_events" in q_str:
            result.all.return_value = []
        else:
            result.first.return_value = None
            result.all.return_value = []
        return result

    def mock_get(model, ident):
        if model == Case:
            return mock_case
        if model == Unit:
            return mock_unit
        if model == Company:
            return company
        return None

    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = mock_get
    mock_sess.__enter__.return_value = mock_sess

    mock_engine = MagicMock()
    mock_wf = MagicMock()

    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        TestClient(app) as client,
    ):
        res = client.post(
            "/api/agent/ask",
            json={"query": "Schedule Kevin to visit Keizersgracht 42-A on Friday at 3 PM"},
        )
        assert res.status_code == 200
        data = res.json()

        # Check answer & previewCard
        assert "Kevin van Dijk" in data["answer"]
        assert data["previewCard"] is not None
        assert data["previewCard"]["type"] == "calendar_item"
        assert data["previewCard"]["unitLabel"] == "Keizersgracht 42-A"
        assert data["previewCard"]["status"] == "proposed"

        # Check action button
        primary_btn = next((b for b in data["actions"] if b["isPrimary"]), None)
        assert primary_btn is not None
        assert "Approve & Add to Google Calendar" in primary_btn["label"]
        assert primary_btn["actionType"] == "approve_calendar"


def test_super_agent_calendar_schedule_inquiry():
    company = Company(id=TEST_COMP_ID, name="EstateOS Test")
    evt = CalendarEventRow(
        id=uuid4(),
        company_id=TEST_COMP_ID,
        title="Plumbing Inspection · Keizersgracht 42-A",
        start_time=datetime(2026, 10, 30, 15, 0, tzinfo=UTC),
        end_time=datetime(2026, 10, 30, 16, 0, tzinfo=UTC),
        location="Keizersgracht 42-A",
        status="confirmed",
        event_type="contractor_repair",
    )

    mock_sess = MagicMock()

    def mock_scalars(query):
        result = MagicMock()
        q_str = str(query).lower()
        if "from companies" in q_str:
            result.first.return_value = company
        elif "from calendar_events" in q_str:
            result.all.return_value = [evt]
        else:
            result.first.return_value = None
            result.all.return_value = []
        return result

    mock_sess.scalars.side_effect = mock_scalars
    mock_sess.get.side_effect = lambda m, i: company if m == Company else None
    mock_sess.__enter__.return_value = mock_sess

    mock_engine = MagicMock()
    mock_wf = MagicMock()

    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        TestClient(app) as client,
    ):
        res = client.post(
            "/api/agent/ask",
            json={"query": "What visits do I have scheduled this week on my calendar?"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "Plumbing Inspection" in data["answer"]
        assert "Keizersgracht 42-A" in data["answer"]
        assert any(b["label"] == "Open Calendar" for b in data["actions"])

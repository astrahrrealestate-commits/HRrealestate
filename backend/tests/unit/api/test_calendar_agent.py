"""Unit and integration tests for the EstateOS Calendar Agent.

Verifies:
1. Natural language time & slot extraction (English & Dutch).
2. Lockbox requirement detection.
3. Fallback when message has no time expressions.
4. FakeCalendarClient CRUD, free/busy, and conflict handling with fake credentials.
5. Conflict resolution & alternative slot proposal.
6. REST API: /api/calendar/propose, /api/calendar/events, and 1-click /api/calendar/events/{id}/approve.
7. Super Agent integration: a planned `calendar` step producing a type="calendar_item" previewCard with 1-click action.
8. Super Agent listing of scheduled visits.
9. The planner, not a word, decides what is a calendar request.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.agent import routes as agent_routes
from app.api.agent.cards import PreviewCardData
from app.api.agent.intent_responses import calendar_segment
from app.channels.calendar import (
    CalendarAttendee,
    CalendarEventCreate,
    CalendarUnavailableError,
    FakeCalendarClient,
)
from app.contracts import CaseState, Category, ConciergePlan, Intent, PlanStep, Urgency
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import CalendarEventRow, Case, Company, Person, Unit
from app.llm.agents.calendar import (
    TimeNotStatedError,
    detect_lockbox_need,
    extract_time_window,
    propose_calendar_event,
)
from app.main import create_app
from app.pipeline.concierge import StepResult
from app.pipeline.concierge_reads import CALENDAR_POINTER
from app.superagent import lookups
from tests.api_auth import as_owner, with_conversation

AMSTERDAM = ZoneInfo("Europe/Amsterdam")

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
        patch("app.api.agent.routes.get_calendar_client", return_value=fake),
    ):
        yield fake


def _step(intent: Intent, *, text: str | None = None, case_id: UUID | None = None) -> PlanStep:
    return PlanStep(intent=intent, case_id=case_id, task_ref=None, text=text, view=None)


def _plan(*steps: PlanStep) -> ConciergePlan:
    return ConciergePlan(in_scope=True, steps=list(steps), reply=None)


# ---------------------------------------------------------------------------
# 1. TIME WINDOW EXTRACTION TESTS
# ---------------------------------------------------------------------------


def test_extract_time_window_range_dutch_and_english():
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=AMSTERDAM)  # Wednesday

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
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=AMSTERDAM)  # Wednesday

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


def test_missing_time_is_never_invented():
    ref = datetime(2026, 10, 28, 9, 0, tzinfo=AMSTERDAM)
    with pytest.raises(TimeNotStatedError):
        extract_time_window("There is a leak under the sink, please send someone", reference_date=ref)
    with pytest.raises(TimeNotStatedError):
        extract_time_window("Kevin can come at 15:00", reference_date=ref)  # a time but no day
    with pytest.raises(TimeNotStatedError):
        extract_time_window("Kevin can come tomorrow", reference_date=ref)  # a day but no time


def test_propose_endpoint_asks_when_no_time_is_stated():
    app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))
    with TestClient(app) as client:
        res = client.post("/api/calendar/propose", json={"messageText": "please come by", "propertyAddress": "X 1"})
    assert res.status_code == 422


def test_no_calendar_connected_is_an_error_not_a_free_calendar():
    app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))
    with (
        patch("app.api.calendar.routes.get_calendar_client", side_effect=CalendarUnavailableError("not connected")),
        TestClient(app) as client,
    ):
        res = client.post("/api/calendar/propose", json={"messageText": "morgen om 15:00", "propertyAddress": "X 1"})
    assert res.status_code == 503


# ---------------------------------------------------------------------------
# 2. FAKE CALENDAR CLIENT CRUD & FREE/BUSY TESTS
# ---------------------------------------------------------------------------


def test_fake_calendar_client_lifecycle():
    client = FakeCalendarClient(credentials={"fake": "mock_test_token"})
    now = datetime(2026, 10, 30, 10, 0, tzinfo=AMSTERDAM)

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
    friday_3pm = datetime(2026, 10, 30, 15, 0, tzinfo=AMSTERDAM)

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
        reference_date=datetime(2026, 10, 28, 9, 0, tzinfo=AMSTERDAM),
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
    mock_sess.get.side_effect = with_conversation(mock_get)
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
    kevin = Person(
        id=uuid4(),
        company_id=TEST_COMP_ID,
        kind=PersonKind.contractor,
        display_name="Kevin van Dijk",
        trade="technician",
    )
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
        elif "from units" in q_str:
            result.all.return_value = [mock_unit]
        elif "from people" in q_str:
            result.all.return_value = [kevin]
            result.first.return_value = kevin
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
    mock_sess.get.side_effect = with_conversation(mock_get)
    mock_sess.__enter__.return_value = mock_sess

    mock_engine = MagicMock()
    mock_wf = MagicMock()

    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))
    query = "Schedule Kevin to visit Keizersgracht 42-A on Friday at 3 PM"

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as planner,
        TestClient(app) as client,
    ):
        planner.return_value.output = _plan(_step(Intent.calendar, text=query))
        res = client.post("/api/agent/ask", json={"query": query})
        assert res.status_code == 200
        data = res.json()
        assert data["debugInfo"]["pipeline_stage"] == "calendar"

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
        start_time=datetime(2026, 10, 30, 15, 0, tzinfo=AMSTERDAM),
        end_time=datetime(2026, 10, 30, 16, 0, tzinfo=AMSTERDAM),
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
    mock_sess.get.side_effect = with_conversation(lambda m, i: company if m == Company else None)
    mock_sess.__enter__.return_value = mock_sess

    mock_engine = MagicMock()
    mock_wf = MagicMock()

    app = as_owner(create_app(SETTINGS, engine=mock_engine, workflow_client=mock_wf))
    query = "What visits do I have scheduled this week on my calendar?"

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.run_agent") as planner,
        TestClient(app) as client,
    ):
        planner.return_value.output = _plan(_step(Intent.calendar, text=query))
        res = client.post("/api/agent/ask", json={"query": query})
        assert res.status_code == 200
        data = res.json()
        assert data["debugInfo"]["pipeline_stage"] == "calendar"
        assert "Plumbing Inspection" in data["answer"]
        assert "Keizersgracht 42-A" in data["answer"]
        assert any(b["label"] == "Open Calendar" for b in data["actions"])


# ---------------------------------------------------------------------------
# 5. THE PLANNER, NOT A WORD, DECIDES WHAT IS A CALENDAR REQUEST
# ---------------------------------------------------------------------------

CASE_ID, UNIT_ID = UUID(int=11), UUID(int=12)
DRAFT_CARD = PreviewCardData(
    type="draft_message",
    channel="whatsapp",
    recipient="+31612345678",
    unitLabel="Keizersgracht 42-A",
    body="Hallo, kan de loodgieter morgen langskomen?",
    status="pending",
    actionId=str(UUID(int=13)),
    caseId=str(CASE_ID),
)
DRAFTED = StepResult(
    Intent.draft_reply, True, "Reply drafted.", {"approval_ids": [str(UUID(int=14))], "case_id": str(CASE_ID)}, None
)


def _portfolio_session() -> MagicMock:
    """One open case on Keizersgracht 42-A, one plumber on file, nothing on the calendar."""
    company = Company(id=TEST_COMP_ID, name="EstateOS Test")
    unit = Unit(id=UNIT_ID, company_id=TEST_COMP_ID, address="Keizersgracht 42-A")
    case = Case(
        id=CASE_ID,
        company_id=TEST_COMP_ID,
        unit_id=UNIT_ID,
        category=Category.maintenance,
        urgency=Urgency.normal,
        state=CaseState.waiting_on_third_party,
        summary="Leaking kitchen tap.",
    )
    plumber = Person(
        id=UUID(int=15),
        company_id=TEST_COMP_ID,
        kind=PersonKind.contractor,
        display_name="Jan Plumber",
        trade="plumber",
    )
    rows: dict[str, list[Any]] = {
        "from companies": [company],
        "from cases": [case],
        "from people": [plumber],
        "from units": [unit],
    }
    by_model: dict[Any, Any] = {Company: company, Case: case, Unit: unit}

    def scalars(query: object) -> MagicMock:
        found = next((r for table, r in rows.items() if table in str(query).lower()), [])
        result = MagicMock()
        result.all.return_value = found
        result.first.return_value = found[0] if found else None
        return result

    sess = MagicMock()
    sess.scalars.side_effect = scalars
    sess.scalar.return_value = None
    sess.get.side_effect = with_conversation(lambda model, _ident: by_model.get(model))
    sess.__enter__.return_value = sess
    return sess


def _ask(
    plan: ConciergePlan, query: str, run_plan: MagicMock | None = None
) -> tuple[dict[str, Any], MagicMock, MagicMock]:
    """Ask with the planner stubbed to `plan`. The calendar helper runs for real behind a spy; a drafted reply resolves
    to `DRAFT_CARD`; no lease document is indexed; no model stands behind the fallback chain."""
    sess = _portfolio_session()
    resolve = MagicMock(wraps=agent_routes._resolve_calendar_action)
    app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))
    with (
        patch("app.api.agent.routes.Session", return_value=sess),
        patch("app.api.agent.routes.run_agent") as planner,
        patch("app.api.agent.routes.run_plan", run_plan or MagicMock(return_value=[])),
        patch("app.api.agent.routes._resolve_calendar_action", resolve),
        patch("app.api.agent.routes._resolve_draft_card", return_value=DRAFT_CARD),
        patch("app.api.agent.routes.search_hybrid", return_value=[]),
        patch("app.api.agent.routes._research_answer", return_value=None),
        patch("app.api.agent.routes._generate_chat_answer", return_value=None),
        TestClient(app) as client,
    ):
        planner.return_value.output = plan
        res = client.post("/api/agent/ask", json={"query": query})
    assert res.status_code == 200
    planner.assert_called_once()
    return res.json(), sess, resolve


def _events_added(sess: MagicMock) -> list[CalendarEventRow]:
    return [c.args[0] for c in sess.add.call_args_list if isinstance(c.args[0], CalendarEventRow)]


def test_calendar_intent_books_a_visit() -> None:
    """No calendar word in the message: the planner's `calendar` step books the visit (its text is the request)."""
    plan = _plan(_step(Intent.calendar, text="book the plumber Thursday at 10:00 at Keizersgracht"))
    data, sess, resolve = _ask(plan, "can the plumber come Thursday at 10:00 at Keizersgracht")

    resolve.assert_called_once()
    assert resolve.call_args.args[0] == "book the plumber Thursday at 10:00 at Keizersgracht"
    assert data["debugInfo"]["pipeline_stage"] == "calendar"
    assert data["previewCard"]["type"] == "calendar_item"
    assert [c["type"] for c in data["cards"]] == ["calendar_item"]
    assert data["cards"][0]["actions"][0]["label"] == "Approve & Add to Calendar"
    assert data["actions"][0]["actionType"] == "approve_calendar"
    assert [e.status for e in _events_added(sess)] == ["proposed"]
    # a proposed visit sets the conversation's focus, as the calendar answer always did
    assert data["focus_state"]["unit_label"] == "Keizersgracht 42-A"
    assert data["focus_state"]["case_id"] == str(CASE_ID)


def test_payment_schedule_is_not_a_calendar_request() -> None:
    answer = "Unit 3 pays its rent on the 1st of each month."
    run_plan = MagicMock(return_value=[StepResult(Intent.answer, True, answer, None, None)])
    data, sess, resolve = _ask(
        _plan(_step(Intent.answer)), "what is the payment schedule for unit 3", run_plan=run_plan
    )

    resolve.assert_not_called()  # the word "schedule" no longer reaches the calendar
    assert data["answer"] == answer
    assert data["debugInfo"]["pipeline_stage"] == "llm_concierge"
    assert all(c["type"] != "calendar_item" for c in data["cards"])
    assert _events_added(sess) == []


def test_draft_that_mentions_a_visit_is_a_draft() -> None:
    run_plan = MagicMock(return_value=[DRAFTED])
    data, sess, resolve = _ask(
        _plan(_step(Intent.draft_reply, case_id=CASE_ID)),
        "Draft a message to the plumber to schedule a visit tomorrow",
        run_plan=run_plan,
    )

    resolve.assert_not_called()
    assert [s.intent for s in run_plan.call_args.args[3].steps] == [Intent.draft_reply]
    assert data["previewCard"]["type"] == "draft_message"
    assert [c["type"] for c in data["cards"]] == ["draft_message"]
    assert _events_added(sess) == []


def test_negated_schedule_books_nothing() -> None:
    lease = "Clause 4: the tenant gives one month notice."
    run_plan = MagicMock(return_value=[StepResult(Intent.read_document, True, lease, None, None)])
    data, sess, resolve = _ask(
        _plan(_step(Intent.read_document, text="lease")),
        "Do NOT schedule a visit yet, just check the lease",
        run_plan=run_plan,
    )

    resolve.assert_not_called()
    assert _events_added(sess) == []
    assert lease in data["answer"]
    assert all(c["type"] != "calendar_item" for c in data["cards"])


def test_calendar_and_draft_in_one_message() -> None:
    run_plan = MagicMock(return_value=[DRAFTED])
    plan = _plan(
        _step(Intent.draft_reply, case_id=CASE_ID),
        _step(Intent.calendar, text="book the plumber Thursday at 10:00 at Keizersgracht"),
    )
    data, sess, _ = _ask(plan, "Draft a reply to the tenant and book the plumber Thursday at 10:00", run_plan=run_plan)

    assert [s.intent for s in run_plan.call_args.args[3].steps] == [Intent.draft_reply]  # calendar never ran twice
    assert [c["type"] for c in data["cards"]] == ["draft_message", "calendar_item"]
    assert [c["type"] for c in data["previewCards"]] == ["draft_message", "calendar_item"]
    assert data["previewCard"]["type"] == "draft_message"
    assert any(a["actionType"] == "approve_calendar" for a in data["actions"])
    assert [e.status for e in _events_added(sess)] == ["proposed"]


def test_a_calendar_step_the_helper_cannot_place_points_to_the_calendar_page() -> None:
    """Nothing to book or look up in the step's text: the pipeline calendar handler's own pointer, no card."""
    segment = calendar_segment((None, None, [], []))
    assert (segment.text, segment.cards, segment.actions, segment.preview_card) == (CALENDAR_POINTER, [], [], None)


# ---------------------------------------------------------------------------
# 6. WHAT GOOGLE SAID REACHES THE OWNER
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query", ["Schedule a focus review Friday at 3 PM", "What visits are on my calendar this week?"]
)
def test_the_calendar_answer_says_why_google_calendar_is_unavailable(query: str) -> None:
    reason = "Your Google sign-in has expired or been revoked."
    client = MagicMock()
    client.check_free_busy.side_effect = CalendarUnavailableError(reason)
    client.list_events.side_effect = CalendarUnavailableError(reason)
    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess
    mock_sess.scalars.return_value.all.return_value = []

    with (
        patch("app.api.agent.routes.Session", return_value=mock_sess),
        patch("app.api.agent.routes.unit_named", return_value=None),
        patch("app.api.agent.routes.get_calendar_client", return_value=client),
    ):
        answer, *_ = agent_routes._resolve_calendar_action(query, MagicMock(), TEST_COMP_ID, [])

    assert reason in (answer or "")
    assert "no upcoming appointments" not in (answer or "")


def test_a_refused_delete_leaves_the_event_uncancelled() -> None:
    event_id = uuid4()
    row = CalendarEventRow(
        id=event_id,
        company_id=TEST_COMP_ID,
        title="Visit",
        start_time=datetime(2026, 10, 30, 15, tzinfo=AMSTERDAM),
        end_time=datetime(2026, 10, 30, 16, tzinfo=AMSTERDAM),
        status="confirmed",
        event_type="meeting",
        external_event_id="g1",
    )
    client = MagicMock()
    client.delete_event.side_effect = CalendarUnavailableError("Reconnect Google.")
    app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))

    with (
        patch("app.api.calendar.routes.Session", return_value=create_test_mock_session({event_id: row})),
        patch("app.api.calendar.routes.get_calendar_client", return_value=client),
        TestClient(app) as http,
    ):
        res = http.post(f"/api/calendar/events/{event_id}/cancel")

    assert res.status_code == 503
    assert res.json()["detail"] == "Reconnect Google."
    assert row.status == "confirmed"


@pytest.mark.parametrize(
    "lookup",
    [
        lambda deps: lookups.calendar_events(deps, 7),
        lambda deps: lookups.calendar_free_busy(deps, "2026-11-30T10:00", "2026-11-30T11:00"),
    ],
)
def test_a_research_lookup_says_why_the_calendar_could_not_be_read(lookup: Any) -> None:
    mock_sess = MagicMock()
    mock_sess.__enter__.return_value = mock_sess
    mock_sess.scalars.return_value.all.return_value = []

    with (
        patch("app.superagent.lookups.Session", return_value=mock_sess),
        patch("app.superagent.lookups.get_calendar_client", side_effect=CalendarUnavailableError("Reconnect Google.")),
    ):
        text, found = lookup(MagicMock())

    assert "Reconnect Google." in text
    assert found == 0

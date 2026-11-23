"""Incoming Google Calendar invites: property-related ones surface, the rest is ignored, RSVP is one owner click."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.calendar import invites
from app.api.calendar.invites import KnownPerson, KnownUnit, match_invite
from app.channels.calendar import FakeCalendarClient
from app.core.settings import Settings
from app.main import create_app
from tests.api_auth import as_owner

SETTINGS = Settings(
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    gmail_credentials_file="",
    _env_file=None,
)
NOW = datetime.now(UTC)
KEVIN = KnownPerson(name="Kevin van Dijk", kind="contractor", trade="plumber")
UNIT = KnownUnit(id=uuid4(), label="Keizersgracht 42-A", address="Keizersgracht 42-A")


def _seed(fake: FakeCalendarClient, title: str, organizer: str | None, **kw: object) -> str:
    start = NOW + timedelta(days=2)
    evt = fake.seed_event(
        title, start, start + timedelta(hours=1), organizer_email=organizer, self_response_status="needsAction", **kw
    )
    return evt.id


def test_match_by_known_organizer_email_ignores_case():
    fake = FakeCalendarClient()
    _seed(fake, "Boiler check", "Kevin@ChahalBouw.nl")
    (event,) = fake.list_pending_invites(NOW, NOW + timedelta(days=5))
    got = match_invite(event, {"kevin@chahalbouw.nl": KEVIN}, [])
    assert got is not None
    assert (got.matchedBy, got.person.name, got.unit) == ("organizer", "Kevin van Dijk", None)  # type: ignore[union-attr]


def test_match_by_unit_address_when_organizer_unknown():
    fake = FakeCalendarClient()
    _seed(fake, "Viewing", "stranger@example.com", location="keizersgracht 42-a, Amsterdam")
    (event,) = fake.list_pending_invites(NOW, NOW + timedelta(days=5))
    got = match_invite(event, {}, [UNIT])
    assert got is not None
    assert (got.matchedBy, got.unit.label, got.person) == ("address", "Keizersgracht 42-A", None)  # type: ignore[union-attr]


def test_unrelated_personal_invite_is_ignored():
    fake = FakeCalendarClient()
    _seed(fake, "Dinner", "friend@example.com", location="Restaurant Vondel")
    (event,) = fake.list_pending_invites(NOW, NOW + timedelta(days=5))
    assert match_invite(event, {"kevin@chahalbouw.nl": KEVIN}, [UNIT]) is None


def test_event_without_organizer_is_ignored():
    fake = FakeCalendarClient()
    _seed(fake, "Own entry", None, location="Keizersgracht 42-A")
    (event,) = fake.list_pending_invites(NOW, NOW + timedelta(days=5))
    assert match_invite(event, {}, [UNIT]) is None


@pytest.fixture
def world():
    fake = FakeCalendarClient()
    ok = _seed(fake, "Boiler check", "kevin@chahalbouw.nl")
    other = _seed(fake, "Dinner", "friend@example.com")
    with (
        patch("app.api.calendar.invites.get_calendar_client", return_value=fake),
        patch.object(invites, "_load_directory", return_value=({"kevin@chahalbouw.nl": KEVIN}, [UNIT])),
        patch.object(invites, "Session", return_value=MagicMock()),
    ):
        app = as_owner(create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock()))
        with TestClient(app) as client:
            yield client, fake, ok, other


def test_list_returns_only_property_invites(world):
    client, _, ok, _ = world
    res = client.get("/api/calendar/invites")
    assert res.status_code == 200
    assert [i["id"] for i in res.json()["invites"]] == [ok]


def test_accept_patches_rsvp(world):
    client, fake, ok, _ = world
    res = client.post(f"/api/calendar/invites/{ok}/respond", json={"response": "accepted"})
    assert res.status_code == 200
    assert fake._events[ok].self_response_status == "accepted"
    assert client.get("/api/calendar/invites").json()["total"] == 0  # answered invites leave the list


def test_decline_patches_rsvp(world):
    client, fake, ok, _ = world
    assert client.post(f"/api/calendar/invites/{ok}/respond", json={"response": "declined"}).status_code == 200
    assert fake._events[ok].self_response_status == "declined"


def test_cannot_answer_unrelated_or_unknown_event(world):
    client, fake, _, other = world
    assert client.post(f"/api/calendar/invites/{other}/respond", json={"response": "accepted"}).status_code == 404
    assert client.post("/api/calendar/invites/nope/respond", json={"response": "accepted"}).status_code == 404
    assert fake._events[other].self_response_status == "needsAction"


def test_invalid_response_is_rejected(world):
    client, _, ok, _ = world
    assert client.post(f"/api/calendar/invites/{ok}/respond", json={"response": "maybe"}).status_code == 422


def _google_item(own_status: str = "needsAction", *, cancelled: bool = False) -> dict:
    return {
        "id": "g1",
        "summary": "Boiler check",
        "status": "cancelled" if cancelled else "confirmed",
        "start": {"dateTime": "2026-12-01T10:00:00+01:00"},
        "end": {"dateTime": "2026-12-01T11:00:00+01:00"},
        "organizer": {"email": "kevin@chahalbouw.nl", "displayName": "Kevin"},
        "attendees": [
            {"email": "kevin@chahalbouw.nl", "responseStatus": "accepted"},
            {"email": "harjot@example.test", "self": True, "responseStatus": own_status},
        ],
    }


def _service(item: dict) -> MagicMock:
    service = MagicMock()
    service.events().list().execute.return_value = {"items": [item]}
    service.events().get().execute.return_value = item
    service.events().patch().execute.side_effect = lambda: item
    return service


def test_google_adapter_lists_only_needs_action_invites_from_others():
    from app.channels.calendar.google import GoogleCalendarClient

    client = GoogleCalendarClient(service=_service(_google_item()))
    (event,) = client.list_pending_invites(NOW, NOW + timedelta(days=60))
    assert (event.organizer_email, event.self_response_status) == ("kevin@chahalbouw.nl", "needsAction")
    assert GoogleCalendarClient(service=_service(_google_item("accepted"))).list_pending_invites(NOW, NOW) == []


def test_google_adapter_rsvp_patches_only_own_attendee_and_notifies_organizer():
    from app.channels.calendar.google import GoogleCalendarClient

    item = _google_item()
    service = _service(item)
    GoogleCalendarClient(service=service).respond_to_invite("g1", "declined")
    kwargs = service.events().patch.call_args.kwargs
    assert kwargs["eventId"] == "g1"
    assert kwargs["sendUpdates"] == "all"
    statuses = {a["email"]: a["responseStatus"] for a in kwargs["body"]["attendees"]}
    assert statuses == {"kevin@chahalbouw.nl": "accepted", "harjot@example.test": "declined"}


def test_google_adapter_rsvp_on_cancelled_event_is_refused():
    from app.channels.calendar.google import GoogleCalendarClient

    service = _service(_google_item(cancelled=True))
    assert GoogleCalendarClient(service=service).respond_to_invite("g1", "accepted") is None


def test_short_or_partial_address_does_not_match_any_location():
    fake = FakeCalendarClient()
    _seed(fake, "Party", "stranger@example.com", location="Flat 1, Keizersgracht 42-AB")
    (event,) = fake.list_pending_invites(NOW, NOW + timedelta(days=5))
    short = KnownUnit(id=uuid4(), label="x", address="1")
    partial = KnownUnit(id=uuid4(), label="y", address="Keizersgracht 42-A")  # inside "42-AB": not the same address
    assert match_invite(event, {}, [short, partial]) is None


def test_dashboard_only_profile_sees_no_invites_and_cannot_answer(world):
    from app.api.v1.auth import Principal
    from app.api.v1.sections import Access
    from tests.api_auth import OWNER, as_owner

    client, fake, ok, _ = world
    viewer = Principal(
        OWNER.company_id,
        OWNER.owner_id,
        "viewer@example.test",
        Access(role="member", sections=frozenset({"dashboard"})),
    )
    as_owner(client.app, viewer)
    assert client.get("/api/calendar/invites").json() == {"invites": [], "total": 0}
    assert client.post(f"/api/calendar/invites/{ok}/respond", json={"response": "accepted"}).status_code == 403
    assert fake._events[ok].self_response_status == "needsAction"


def test_invite_that_closed_before_the_click_is_a_409(world):
    client, fake, ok, _ = world
    with patch.object(fake, "respond_to_invite", return_value=None):
        res = client.post(f"/api/calendar/invites/{ok}/respond", json={"response": "accepted"})
    assert res.status_code == 409


def test_google_adapter_http_error_on_rsvp_is_none_not_a_crash():
    from googleapiclient.errors import HttpError

    from app.channels.calendar.google import GoogleCalendarClient

    service = _service(_google_item())
    service.events().get().execute.side_effect = HttpError(MagicMock(status=404), b"gone")
    assert GoogleCalendarClient(service=service).respond_to_invite("g1", "accepted") is None


def test_google_adapter_skips_one_malformed_event_and_keeps_the_rest():
    from app.channels.calendar.google import GoogleCalendarClient

    bad = {"summary": "no id", "start": {"dateTime": "not-a-date"}}
    service = _service(_google_item())
    service.events().list().execute.return_value = {"items": [bad, _google_item()]}
    events = GoogleCalendarClient(service=service).list_events(NOW, NOW + timedelta(days=60))
    assert [e.id for e in events] == ["g1"]

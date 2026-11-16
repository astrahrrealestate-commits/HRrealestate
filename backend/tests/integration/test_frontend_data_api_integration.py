"""REST endpoints the frontend reads (dashboard, maintenance, properties, tenants, inbox), against a seeded database.

Every number is checked against rows this module seeds, for the signed-in company only: a second company with its own
units, cases and sends must not show up, and nothing is made up when a table is empty.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.contracts import ActionType, Category, Channel, Urgency
from app.core.settings import Settings
from app.db.enums import CaseEventKind, PersonKind, SendStatus, WaitStatus
from app.db.models import (
    ActionRow,
    Case,
    CaseEvent,
    ChannelIdentity,
    Company,
    Lease,
    LeaseParty,
    Person,
    Send,
    TicketEdit,
    Unit,
    WaitRow,
)  # fmt: skip
from app.main import create_app
from tests.api_auth import as_owner
from tests.integration.conftest import purge_company
from tests.integration.test_inbox_maintenance_approve import _seed

pytestmark = pytest.mark.integration
TODAY = datetime.now(UTC).date()
SINCE = date(2025, 3, 1)


@dataclass
class Portfolio:
    client: TestClient
    engine: Engine
    company: UUID
    singel: UUID  # occupied, open-ended lease
    prinsen: UUID  # occupied, lease ending soon -> notice given
    herengracht: UUID  # vacant
    anouk: UUID
    maintenance_case: UUID


def _unit(s: Session, company_id: UUID, label: str, address: str) -> UUID:
    unit = Unit(company_id=company_id, label=label, address=address, valid_from=date(2024, 1, 1))
    s.add(unit)
    s.flush()
    return unit.id


def _tenant(s: Session, company_id: UUID, unit_id: UUID, name: str, email: str, phone: str, end: date | None) -> UUID:
    person = Person(company_id=company_id, kind=PersonKind.tenant, display_name=name, valid_from=SINCE)
    lease = Lease(company_id=company_id, unit_id=unit_id, valid_from=SINCE, valid_to=end)
    s.add_all([person, lease])
    s.flush()
    s.add_all(
        [
            LeaseParty(company_id=company_id, lease_id=lease.id, person_id=person.id, role="tenant"),
            ChannelIdentity(
                company_id=company_id, person_id=person.id, channel=Channel.gmail, identity=email, valid_from=SINCE
            ),
            ChannelIdentity(
                company_id=company_id, person_id=person.id, channel=Channel.whatsapp, identity=phone, valid_from=SINCE
            ),
        ]
    )
    s.flush()
    return person.id


def _send(s: Session, company_id: UUID, days_ago: int) -> None:
    s.add(
        Send(
            company_id=company_id, idempotency_key=f"k-{uuid4()}", channel=Channel.gmail, target="x@y.test",
            status=SendStatus.sent, attempted_at=datetime.now(UTC) - timedelta(days=days_ago),
        )
    )  # fmt: skip


@pytest.fixture
def portfolio(migrated_engine: Engine, pg_url: str) -> Iterator[Portfolio]:
    with Session(migrated_engine) as s:
        mine, theirs = Company(name="Data A"), Company(name="Data B")
        s.add_all([mine, theirs])
        s.flush()
        a, b = mine.id, theirs.id
        singel = _unit(s, a, "Singel 5-A", "Singel 5-A, 1012 AB Amsterdam")
        prinsen = _unit(s, a, "Prinsengracht 9", "Prinsengracht 9, 1015 DK Amsterdam")
        herengracht = _unit(s, a, "Herengracht 1", "Herengracht 1, 1015 BA Amsterdam")
        anouk = _tenant(s, a, singel, "Anouk de Vries", "anouk@a.test", "+31611111111", None)
        bram = _tenant(s, a, prinsen, "Bram Jansen", "bram@a.test", "+31622222222", TODAY + timedelta(days=30))
        # an emergency maintenance case and the seeded inbox case (urgency high, one pending approval)
        emergency = Case(company_id=a, category=Category.maintenance, urgency=Urgency.emergency, summary="Burst pipe")
        s.add(emergency)
        s.flush()
        _seed(s, mine, suspicious=False)
        s.add(
            CaseEvent(company_id=a, case_id=emergency.id, kind=CaseEventKind.note, note="Plumber called", actor="owner")
        )
        s.add(
            WaitRow(
                company_id=a, case_id=emergency.id, party_person_id=bram, about="Quote for the pipe",
                expected_by=datetime.now(UTC) - timedelta(days=4), status=WaitStatus.waiting,
            )
        )  # fmt: skip
        _send(s, a, 1)
        _send(s, a, 3)
        _send(s, a, 30)  # outside the week
        # another company: must stay invisible in every count below
        other_unit = _unit(s, b, "Elsewhere 1", "Elsewhere 1")
        _tenant(s, b, other_unit, "Carla Smit", "carla@b.test", "+31633333333", None)
        s.add(Case(company_id=b, category=Category.maintenance, urgency=Urgency.emergency, summary="Their burst pipe"))
        _send(s, b, 1)
        s.commit()
        emergency_id = emergency.id
        ids = (a, b)
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=ids[0], owner_id=uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=migrated_engine), owner)
    with TestClient(app) as client:
        yield Portfolio(client, migrated_engine, ids[0], singel, prinsen, herengracht, anouk, emergency_id)
    for company_id in ids:
        purge_company(migrated_engine, company_id)


# ============================================================================
# 1. Dashboard
# ============================================================================


def test_dashboard_pulse_counts_only_this_companys_real_rows(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/dashboard/pulse").json()
    assert data["totalUnits"] == 3
    assert data["occupiedUnits"] == 2
    assert data["occupancyPercentage"] == 66.7
    assert data["emergencyCount"] == 1  # theirs is not counted
    assert data["needsYouCount"] == 1  # the one seeded pending approval
    assert data["autonomousActionsWeek"] == 2  # two sends this week; the 30 day old one and theirs are not counted
    assert data["rentDataAvailable"] is False
    assert (data["openRentTotalEur"], data["overdueRentEur"], data["hoursSavedWeek"]) == (0.0, 0.0, 0.0)


def test_the_pulse_of_an_empty_company_is_zeros_not_invented_numbers(migrated_engine: Engine, pg_url: str) -> None:
    with Session(migrated_engine) as s:
        empty = Company(name="Empty")
        s.add(empty)
        s.commit()
        company_id = empty.id
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=company_id, owner_id=uuid4(), email="harjot@example.test")
    try:
        with TestClient(as_owner(create_app(settings, engine=migrated_engine), owner)) as client:
            data = client.get("/api/dashboard/pulse").json()
        assert (data["totalUnits"], data["occupiedUnits"], data["occupancyPercentage"]) == (0, 0, 0.0)
        assert (data["needsYouCount"], data["emergencyCount"], data["autonomousActionsWeek"]) == (0, 0, 0)
    finally:
        purge_company(migrated_engine, company_id)


def test_dashboard_radar_lists_overdue_waits_with_who_where_and_how_long(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/dashboard/radar").json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["partyName"] == "Bram Jansen"
    assert item["partyRole"] == "tenant"
    assert item["issueSummary"] == "Quote for the pipe"
    assert item["daysWaiting"] == 4
    assert item["proposedActionLabel"]


def test_dashboard_inquiries_are_empty_until_inquiries_exist(portfolio: Portfolio) -> None:
    assert portfolio.client.get("/api/dashboard/inquiries").json() == {"inquiries": [], "total": 0}


def test_dashboard_logs_list_this_companys_sent_replies_newest_first(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/dashboard/logs?limit=5").json()
    assert data["total"] == 3  # theirs excluded
    assert all(entry["actionText"] == "Sent an approved gmail reply" for entry in data["logs"])
    stamps = [entry["timestamp"] for entry in data["logs"]]
    assert stamps == sorted(stamps, reverse=True)


def test_the_briefing_states_only_what_the_database_holds(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/dashboard/briefing").json()
    text = str(data)
    assert "2 matters need attention" in text  # the emergency case and the seeded high-urgency inbox case
    assert "1 draft awaiting your review" in text
    for invented in ("94.5", "120.400", "Keizersgracht", "Pieter Floriszstraat", "FastFix"):
        assert invented not in text


# ============================================================================
# 2. Maintenance hub
# ============================================================================


def test_maintenance_tickets_list_this_companys_cases(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/maintenance/tickets").json()
    assert "stats" in data
    ids = {t["id"] for t in data["tickets"]}
    assert str(portfolio.maintenance_case) in ids
    ticket = next(t for t in data["tickets"] if t["id"] == str(portfolio.maintenance_case))
    for key in ("ticketNumber", "issueTitle", "unitLabel", "contractorName", "poBudgetCap", "slaRemaining"):
        assert key in ticket
    assert "Their burst pipe" not in str(data)


def test_a_ticket_with_no_recorded_facts_shows_none_instead_of_invented_ones(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/maintenance/tickets").json()
    ticket = next(t for t in data["tickets"] if t["id"] == str(portfolio.maintenance_case))
    assert ticket["issueTitle"] == "Burst pipe"
    assert (ticket["contractorName"], ticket["contractorPhone"], ticket["contractorEmail"]) == ("", "", "")
    assert (ticket["poBudgetCap"], ticket["slaRemaining"], ticket["tenantPhone"]) == ("", "", "")
    assert (ticket["category"], ticket["unitLabel"]) == ("other", "Unknown unit")
    assert data["stats"]["totalPoBudgetEur"] == 0
    rendered = str(ticket)
    for invented in ("Kevin", "chahalbouw", "650", "kitchen sink", "Keizersgracht", "+31 6 88", "+91"):
        assert invented not in rendered


def test_the_contractor_comes_from_the_requested_action_and_sets_the_category(portfolio: Portfolio) -> None:
    with Session(portfolio.engine) as s:
        person = Person(
            company_id=portfolio.company, kind=PersonKind.contractor, display_name="Piet Loodgieter",
            trade="plumber", valid_from=SINCE,
        )  # fmt: skip
        s.add(person)
        s.flush()
        s.add(
            ChannelIdentity(
                company_id=portfolio.company, person_id=person.id, channel=Channel.whatsapp,
                identity="+31699999999", valid_from=SINCE,
            )
        )  # fmt: skip
        s.add(
            ActionRow(
                company_id=portfolio.company, case_id=portfolio.maintenance_case, type=ActionType.request_contractor,
                payload={
                    "kind": "request_contractor",
                    "contractor_person_id": str(person.id),
                    "body_variants": ["Hoi Piet, graag langskomen."],
                },
                rationale="r", context_ref=[],
            )
        )  # fmt: skip
        s.commit()
    data = portfolio.client.get("/api/maintenance/tickets").json()
    ticket = next(t for t in data["tickets"] if t["id"] == str(portfolio.maintenance_case))
    assert (ticket["contractorName"], ticket["contractorTrade"], ticket["contractorPhone"]) == (
        "Piet Loodgieter", "Plumber", "+31699999999",
    )  # fmt: skip
    assert (ticket["category"], ticket["contractorDraft"]) == ("plumbing", "Hoi Piet, graag langskomen.")


def test_maintenance_tickets_filtering(portfolio: Portfolio) -> None:
    res = portfolio.client.get("/api/maintenance/tickets?category=electrical")
    assert res.status_code == 200
    assert all(t["category"] == "electrical" for t in res.json()["tickets"])


def test_maintenance_ticket_history_is_the_persisted_case_trail(portfolio: Portfolio) -> None:
    data = portfolio.client.get(f"/api/maintenance/tickets/{portfolio.maintenance_case}/history").json()
    assert data["ticketId"] == str(portfolio.maintenance_case)
    assert [e["description"] for e in data["events"]] == ["Plumber called"]
    assert {"actor", "title", "type"} <= set(data["events"][0])


def test_maintenance_ticket_approve_of_an_unknown_ticket_is_not_found(portfolio: Portfolio) -> None:
    """Approving a ticket the company does not have is a 404, never a made-up authorization."""
    res = portfolio.client.post("/api/maintenance/tickets/005/approve", json={"approval_note": "Approved"})
    assert res.status_code == 404


# ============================================================================
# 3. Properties & units
# ============================================================================


def test_properties_list_the_companys_units_with_occupancy_from_leases(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/properties").json()
    assert (data["totalUnits"], data["occupiedCount"], data["vacantCount"]) == (3, 2, 1)
    by_label = {u["label"]: u for u in data["units"]}
    assert set(by_label) == {"Singel 5-A", "Prinsengracht 9", "Herengracht 1"}
    assert (by_label["Singel 5-A"]["status"], by_label["Singel 5-A"]["currentTenant"]) == ("occupied", "Anouk de Vries")
    assert by_label["Prinsengracht 9"]["status"] == "notice_given"
    assert by_label["Prinsengracht 9"]["leaseEnd"] == f"{TODAY + timedelta(days=30):%d-%m-%Y}"
    assert (by_label["Herengracht 1"]["status"], by_label["Herengracht 1"]["currentTenant"]) == ("vacant", None)
    for unit in data["units"]:
        assert unit["lockboxCode"] is None  # never exposed
        assert unit["monthlyRentEur"] == 0.0
    assert "Elsewhere" not in str(data)


def test_properties_filter_by_status_and_single_unit_lookup(portfolio: Portfolio) -> None:
    vacant = portfolio.client.get("/api/properties?status=vacant").json()
    assert [u["label"] for u in vacant["units"]] == ["Herengracht 1"]
    assert vacant["totalUnits"] == 3  # the counts describe the portfolio, the list is filtered
    one = portfolio.client.get(f"/api/properties/{portfolio.singel}")
    assert (one.status_code, one.json()["address"]) == (200, "Singel 5-A, 1012 AB Amsterdam")


def test_a_unit_of_another_company_or_a_bad_id_is_not_found(portfolio: Portfolio) -> None:
    assert portfolio.client.get(f"/api/properties/{uuid4()}").status_code == 404
    assert portfolio.client.get("/api/properties/not-a-uuid").status_code == 404


# ============================================================================
# 4. Tenants
# ============================================================================


def test_tenants_list_the_companys_tenants_with_lease_facts_and_unknown_rent(portfolio: Portfolio) -> None:
    data = portfolio.client.get("/api/tenants").json()
    assert (data["totalTenants"], data["overdueCount"]) == (2, 0)
    anouk = next(t for t in data["tenants"] if t["name"] == "Anouk de Vries")
    assert (anouk["email"], anouk["phone"], anouk["unitLabel"]) == ("anouk@a.test", "+31611111111", "Singel 5-A")
    assert (anouk["leaseStart"], anouk["leaseEnd"]) == ("01-03-2025", "")
    assert (anouk["rentStatus"], anouk["monthlyRentEur"]) == ("unknown", 0.0)
    assert "Carla" not in str(data)


def test_tenant_profile_lookup_is_scoped(portfolio: Portfolio) -> None:
    ok = portfolio.client.get(f"/api/tenants/{portfolio.anouk}")
    assert (ok.status_code, ok.json()["name"]) == (200, "Anouk de Vries")
    assert portfolio.client.get(f"/api/tenants/{uuid4()}").status_code == 404
    assert portfolio.client.get("/api/tenants/Anouk").status_code == 404


# ============================================================================
# 5. Inbox & CORS
# ============================================================================


def test_inbox_threads_api(portfolio: Portfolio) -> None:
    res = portfolio.client.get("/api/inbox/threads")
    assert res.status_code == 200
    assert "threads" in res.json()


def test_cors_headers_for_frontend(test_settings: Settings, migrated_engine: Engine) -> None:
    """An allowlisted SPA origin (DASHBOARD_CORS_ORIGINS) passes the preflight; without one, CORS is off outside dev."""
    settings = test_settings.model_copy(update={"dashboard_cors_origins": ["http://localhost:3000"]})
    headers = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    with TestClient(create_app(settings, engine=migrated_engine)) as client:
        res = client.options("/api/dashboard/pulse", headers=headers)
    assert res.status_code in (200, 204)
    assert res.headers.get("access-control-allow-origin") in ("http://localhost:3000", "*")


def test_owner_ticket_edits_persist_in_postgres_and_the_audit_trail(portfolio: Portfolio) -> None:
    """Edits must live in the database (invariant 1), not a process dict: the list reflects them and a case event
    records them."""
    res = portfolio.client.patch(
        f"/api/maintenance/tickets/{portfolio.maintenance_case}",
        json={"poBudgetCap": "EUR 350", "contractorTrade": "plumbing"},
    )
    assert res.status_code == 200
    listed = portfolio.client.get("/api/maintenance/tickets").json()
    ticket = next(t for t in listed["tickets"] if t["id"] == str(portfolio.maintenance_case))
    assert (ticket["poBudgetCap"], ticket["contractorTrade"]) == ("EUR 350", "plumbing")
    with Session(portfolio.engine) as s:
        edit = s.scalars(select(TicketEdit).where(TicketEdit.company_id == portfolio.company)).one()
        assert edit.case_id == portfolio.maintenance_case
        assert edit.fields["poBudgetCap"] == "EUR 350"
    history = portfolio.client.get(f"/api/maintenance/tickets/{portfolio.maintenance_case}/history").json()
    assert any(e["actorType"] == "owner" and "edited" in e["description"].lower() for e in history["events"])


def test_editing_an_unknown_ticket_is_a_404_not_an_invented_row(portfolio: Portfolio) -> None:
    res = portfolio.client.patch("/api/maintenance/tickets/does-not-exist", json={"poBudgetCap": "EUR 1"})
    assert res.status_code == 404


def test_contractor_identity_edits_are_display_only_and_never_persist(portfolio: Portfolio) -> None:
    """Who a dispatch goes to comes from the case's request_contractor action (invariant 5): a persisted name
    override would let the dashboard show someone other than the real recipient."""
    res = portfolio.client.patch(
        f"/api/maintenance/tickets/{portfolio.maintenance_case}",
        json={"contractorName": "Someone Else", "contractorEmail": "else@x.test", "contractorPhone": "+31600000000"},
    )
    assert res.status_code == 200
    listed = portfolio.client.get("/api/maintenance/tickets").json()
    ticket = next(t for t in listed["tickets"] if t["id"] == str(portfolio.maintenance_case))
    assert (ticket["contractorName"], ticket["contractorEmail"], ticket["contractorPhone"]) == ("", "", "")
    with Session(portfolio.engine) as s:
        for edit in s.scalars(select(TicketEdit).where(TicketEdit.company_id == portfolio.company)):
            assert not {"contractorName", "contractorEmail", "contractorPhone"} & set(edit.fields)


def test_erasing_the_tenant_deletes_the_ticket_edits_of_their_cases(portfolio: Portfolio) -> None:
    from app.pipeline.gdpr import erase_person

    portfolio.client.patch(
        f"/api/maintenance/tickets/{portfolio.maintenance_case}",
        json={"tenantDraft": "Beste Anouk, we sturen vandaag iemand langs."},
    )
    with Session(portfolio.engine) as s:
        case = s.get(Case, portfolio.maintenance_case)
        assert case is not None
        case.primary_person_id = portfolio.anouk
        s.commit()
    with Session(portfolio.engine) as s, s.begin():
        erase_person(s, portfolio.company, portfolio.anouk)
    with Session(portfolio.engine) as s:
        left = s.scalars(
            select(TicketEdit).where(
                TicketEdit.company_id == portfolio.company, TicketEdit.case_id == portfolio.maintenance_case
            )
        ).all()
    assert left == []


def _brixx_ticket(portfolio: Portfolio, key: int, title: str, *, urgent: int) -> None:
    from sqlalchemy import text

    with Session(portfolio.engine) as s:
        s.execute(
            text(
                "insert into brixx.tst_ticket (company_id, tst_ticketid, titel, indurgent, indverwijderd, newdatetime)"
                " values (:c, :k, :t, :u, 0, now())"
            ),
            {"c": portfolio.company, "k": key, "t": title, "u": urgent},
        )
        s.commit()


def test_brixx_tickets_reach_the_pulse_the_attention_list_and_the_briefing(portfolio: Portfolio) -> None:
    _brixx_ticket(portfolio, 9001, "Lekkage keuken", urgent=1)
    _brixx_ticket(portfolio, 9002, "Deurbel", urgent=0)
    pulse = portfolio.client.get("/api/dashboard/pulse").json()
    assert pulse["emergencyCount"] == 2  # the seeded emergency case plus the BRIXX ticket flagged urgent
    attention = portfolio.client.get("/api/dashboard/attention").json()
    assert (attention["total"], attention["urgentCount"]) == (2, 1)
    assert [i["title"] for i in attention["items"]] == ["Lekkage keuken", "Deurbel"]  # urgent first
    assert {i["source"] for i in attention["items"]} == {"brixx"}
    briefing = str(portfolio.client.get("/api/dashboard/briefing").json())
    assert "3 matters need attention" in briefing  # the two seeded cases and the urgent BRIXX ticket
    assert "Open BRIXX tickets" in briefing
    assert portfolio.client.get("/api/dashboard/attention?limit=1").json()["total"] == 2


def test_a_company_without_brixx_data_has_an_empty_attention_list(portfolio: Portfolio) -> None:
    assert portfolio.client.get("/api/dashboard/attention").json() == {"items": [], "total": 0, "urgentCount": 0}

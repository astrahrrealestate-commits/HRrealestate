"""Integration tests verifying backend REST API endpoints consumed by the EstateOS frontend.

Tests pure data connectivity, response models, query parameter filtering, and CORS support
without requiring mock LLM agent execution or workflow triggers.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.api.v1.auth import Principal
from app.core.settings import Settings
from app.db.models import Company
from app.main import create_app
from tests.api_auth import as_owner

pytestmark = pytest.mark.integration


@pytest.fixture
def api_client(test_settings: Settings, migrated_engine: Engine, committed_company: Company) -> Iterator[TestClient]:
    """A TestClient on the migrated test database, signed in as the owner of a committed company."""
    owner = Principal(company_id=committed_company.id, owner_id=uuid4(), email="harjot@example.test")
    with TestClient(as_owner(create_app(test_settings, engine=migrated_engine), owner)) as client:
        yield client


# ============================================================================
# 1. Dashboard Pulse & Metrics APIs
# ============================================================================


def test_dashboard_pulse_endpoint(api_client: TestClient) -> None:
    """Verifies GET /api/dashboard/pulse returns pulse pillars and portfolio stats."""
    res = api_client.get("/api/dashboard/pulse")
    assert res.status_code == 200
    data = res.json()
    assert "needsYouCount" in data
    assert "emergencyCount" in data
    assert "openRentTotalEur" in data
    assert "overdueRentEur" in data
    assert "occupancyPercentage" in data
    assert "totalUnits" in data
    assert "occupiedUnits" in data
    assert "autonomousActionsWeek" in data
    assert data["totalUnits"] == 110


def test_dashboard_radar_endpoint(api_client: TestClient) -> None:
    """Verifies GET /api/dashboard/radar returns stalled wait items."""
    res = api_client.get("/api/dashboard/radar")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    if data["items"]:
        item = data["items"][0]
        assert "unitLabel" in item
        assert "partyName" in item
        assert "partyRole" in item
        assert "proposedActionLabel" in item


def test_dashboard_inquiries_endpoint(api_client: TestClient) -> None:
    """Verifies GET /api/dashboard/inquiries returns prospective tenant leads."""
    res = api_client.get("/api/dashboard/inquiries")
    assert res.status_code == 200
    data = res.json()
    assert "inquiries" in data
    assert "total" in data
    assert isinstance(data["inquiries"], list)
    assert data["total"] >= 2
    lead = data["inquiries"][0]
    assert "name" in lead
    assert "contact" in lead
    assert "channel" in lead
    assert "unit" in lead


def test_dashboard_logs_endpoint(api_client: TestClient) -> None:
    """Verifies GET /api/dashboard/logs returns autonomous action audit logs."""
    res = api_client.get("/api/dashboard/logs")
    assert res.status_code == 200
    data = res.json()
    assert "logs" in data
    assert "total" in data
    assert isinstance(data["logs"], list)
    log_item = data["logs"][0]
    assert "actionText" in log_item
    assert "timestamp" in log_item
    assert "tag" in log_item


# ============================================================================
# 2. Maintenance Hub APIs
# ============================================================================


def test_maintenance_tickets_list(api_client: TestClient) -> None:
    """Verifies GET /api/maintenance/tickets returns ticket records and operational stats."""
    res = api_client.get("/api/maintenance/tickets")
    assert res.status_code == 200
    data = res.json()
    assert "tickets" in data
    assert "stats" in data
    assert isinstance(data["tickets"], list)
    assert len(data["tickets"]) > 0
    ticket = data["tickets"][0]
    assert "ticketNumber" in ticket
    assert "issueTitle" in ticket
    assert "unitLabel" in ticket
    assert "contractorName" in ticket
    assert "poBudgetCap" in ticket
    assert "slaRemaining" in ticket


def test_maintenance_tickets_filtering(api_client: TestClient) -> None:
    """Verifies filtering by category on GET /api/maintenance/tickets."""
    res = api_client.get("/api/maintenance/tickets?category=electrical")
    assert res.status_code == 200
    data = res.json()
    for ticket in data["tickets"]:
        assert ticket["category"] == "electrical"


def test_maintenance_ticket_full_history(api_client: TestClient) -> None:
    """Verifies GET /api/maintenance/tickets/{ticket_id}/history returns audit trail."""
    res = api_client.get("/api/maintenance/tickets/005/history")
    assert res.status_code == 200
    data = res.json()
    assert "ticketNumber" in data
    assert "events" in data
    assert isinstance(data["events"], list)
    assert len(data["events"]) > 0
    event = data["events"][0]
    assert "actor" in event
    assert "title" in event
    assert "type" in event


def test_maintenance_ticket_approve_of_an_unknown_ticket_is_not_found(api_client: TestClient) -> None:
    """Approving a ticket the company does not have is a 404, never a made-up authorization."""
    res = api_client.post("/api/maintenance/tickets/005/approve", json={"approval_note": "Approved by Harjot Singh"})
    assert res.status_code == 404


# ============================================================================
# 3. Properties & Units APIs
# ============================================================================


def test_properties_list_and_details(api_client: TestClient) -> None:
    """Verifies GET /api/properties directory and single unit lookups."""
    res = api_client.get("/api/properties")
    assert res.status_code == 200
    data = res.json()
    assert "units" in data
    assert data["totalUnits"] == 110
    unit = data["units"][0]
    assert "label" in unit
    assert "address" in unit
    assert "monthlyRentEur" in unit

    # Single unit detail lookup
    unit_res = api_client.get(f"/api/properties/{unit['id']}")
    assert unit_res.status_code == 200
    unit_data = unit_res.json()
    assert unit_data["id"] == unit["id"]


# ============================================================================
# 4. Tenants APIs
# ============================================================================


def test_tenants_list_and_details(api_client: TestClient) -> None:
    """Verifies GET /api/tenants directory and single tenant profile."""
    res = api_client.get("/api/tenants")
    assert res.status_code == 200
    data = res.json()
    assert "tenants" in data
    assert "totalTenants" in data
    tenant = data["tenants"][0]
    assert "name" in tenant
    assert "phone" in tenant
    assert "email" in tenant
    assert "unitLabel" in tenant
    assert "rentStatus" in tenant

    # Single tenant profile lookup
    tenant_res = api_client.get(f"/api/tenants/{tenant['id']}")
    assert tenant_res.status_code == 200
    tenant_data = tenant_res.json()
    assert tenant_data["id"] == tenant["id"]


# ============================================================================
# 5. Inbox Endpoints & CORS Validation
# ============================================================================


def test_inbox_threads_api(api_client: TestClient) -> None:
    """Verifies GET /api/inbox/threads for communications triage."""
    res = api_client.get("/api/inbox/threads")
    assert res.status_code == 200
    data = res.json()
    assert "threads" in data


def test_cors_headers_for_frontend(test_settings: Settings, migrated_engine: Engine) -> None:
    """An allowlisted SPA origin (DASHBOARD_CORS_ORIGINS) passes the preflight; without one, CORS is off outside dev."""
    settings = test_settings.model_copy(update={"dashboard_cors_origins": ["http://localhost:3000"]})
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    }
    with TestClient(create_app(settings, engine=migrated_engine)) as client:
        res = client.options("/api/dashboard/pulse", headers=headers)
    assert res.status_code in (200, 204)
    assert res.headers.get("access-control-allow-origin") in ("http://localhost:3000", "*")

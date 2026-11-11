"""Section access: what a profile may open, and the guards that enforce it (profile lookup patched, no database)."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.api.v1.sections import SECTION_KEYS, SECTIONS, Access
from app.core.settings import Settings
from app.main import create_app
from app.pipeline.global_search import HitKind, SearchHit

SETTINGS = Settings(  # type: ignore[call-arg]
    database_url="postgresql+psycopg://u:p@localhost:1/db",
    env="test",
    dashboard_session_secret=SecretStr("x" * 32),
    _env_file=None,
)
PRINCIPAL = Principal(company_id=UUID(int=1), owner_id=UUID(int=2), email="clerk@example.test")


def test_the_catalogue_has_unique_keys_in_sidebar_order() -> None:
    keys = [s.key for s in SECTIONS]
    assert len(keys) == len(SECTION_KEYS)
    assert keys[:2] == ["dashboard", "inbox"]


@pytest.mark.parametrize("role", ["owner", "superadmin"])
def test_admin_roles_open_everything_whatever_the_list_says(role: str) -> None:
    access = Access(role=role, sections=frozenset())
    assert access.is_admin
    assert access.visible_sections() == [s.key for s in SECTIONS]


def test_no_section_list_means_every_section() -> None:
    assert Access(role="manager", sections=None).visible_sections() == [s.key for s in SECTIONS]


def test_a_member_opens_only_the_granted_sections_in_catalogue_order() -> None:
    access = Access(role="member", sections=frozenset({"tenants", "contacts"}))
    assert not access.is_admin
    assert access.visible_sections() == ["tenants", "contacts"]
    assert access.can("contacts")
    assert not access.can("money")


def test_a_member_with_an_empty_list_opens_nothing() -> None:
    assert Access(role="member", sections=frozenset()).visible_sections() == []


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(SETTINGS, engine=MagicMock(), workflow_client=MagicMock())
    with TestClient(app, raise_server_exceptions=False) as c:
        c.cookies.set(COOKIE, issue_session(SETTINGS, PRINCIPAL, datetime.now(UTC)))
        yield c


def _as(access: Access | None) -> "patch[MagicMock]":  # type: ignore[type-arg]
    return patch("app.api.v1.auth.access_for", return_value=access)


def test_a_section_the_profile_lacks_is_a_403_before_any_handler_runs(client: TestClient) -> None:
    with _as(Access(role="member", sections=frozenset({"contacts"}))):
        for path in ("/api/tenants", "/api/properties", "/api/maintenance/tickets", "/api/inbox/threads"):
            assert client.get(path).status_code == 403, path


def test_a_granted_section_passes_the_guard(client: TestClient) -> None:
    with _as(Access(role="member", sections=frozenset({"tenants"}))):
        assert client.get("/api/tenants").status_code != 403


def test_reports_may_read_report_data_but_not_use_the_contacts_section(client: TestClient) -> None:
    with _as(Access(role="member", sections=frozenset({"reports"}))):
        assert client.get("/api/maintenance/tickets").status_code != 403
        add = client.post(
            "/api/contacts", json={"name": "X", "category": "other"}, headers={"X-EstateOS-Client": "dashboard"}
        )
        assert add.status_code == 403
        assert "no access" in add.json()["detail"]


def test_a_switched_off_profile_is_a_401(client: TestClient) -> None:
    with _as(None):
        assert client.get("/api/contacts").status_code == 401


def test_only_admins_reach_the_admin_api(client: TestClient) -> None:
    with _as(Access(role="member", sections=frozenset(SECTION_KEYS))):
        assert client.get("/api/v1/admin/profiles").status_code == 403
    with _as(Access(role="superadmin")):
        assert client.get("/api/v1/admin/sections").status_code == 200


# What a profile with only `contacts` can still reach: its own section and the pages everyone needs. The Super Agent
# is not among them: it answers from the whole portfolio, so only a profile that opens every data section may use it.
# The search palette is shared (it filters its hits by section).
SHARED_PREFIXES = (
    "/api/contacts",
    "/api/v1/auth/session",
    "/api/v1/me",
    "/api/v1/search",
    "/api/v1/feed",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/me",
    "/api/auth/google/callback",
    "/health",
    "/api/webhooks",
    "/webhooks",
)
STREAMING = {"/api/v1/events"}  # an SSE stream never ends; its guard is the same dependency as the rest
CSRF = {"X-EstateOS-Client": "dashboard"}


def test_a_contacts_only_profile_is_refused_on_every_other_route(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    reachable: list[str] = []
    with _as(Access(role="member", sections=frozenset({"contacts"}))):
        for path, operations in sorted(paths.items()):
            if path in STREAMING:
                continue
            for verb in ("get", "post", "put", "patch", "delete"):
                if verb not in operations:
                    continue
                url = re.sub(r"\{[^}]+\}", "00000000-0000-0000-0000-000000000001", path)
                response = client.request(verb.upper(), url, json={} if verb != "get" else None, headers=CSRF)
                if response.status_code != 403 and not path.startswith(SHARED_PREFIXES):
                    reachable.append(f"{response.status_code} {verb.upper()} {path}")
    assert reachable == [], "not behind a section guard: " + ", ".join(reachable)


def test_the_super_agent_needs_every_data_section_because_it_answers_from_the_whole_portfolio(
    client: TestClient,
) -> None:
    ask = {"query": "who is late with rent?"}
    with _as(Access(role="member", sections=frozenset({"contacts", "reports"}))):
        assert client.post("/api/agent/ask", json=ask, headers=CSRF).status_code == 403
        assert client.get("/api/agent/conversations").status_code == 403
    data_sections = frozenset(SECTION_KEYS - {"settings"})
    with _as(Access(role="member", sections=data_sections)):
        assert client.post("/api/agent/ask", json=ask, headers=CSRF).status_code != 403
        assert client.get("/api/agent/conversations").status_code != 403
    with _as(Access(role="superadmin")):
        assert client.get("/api/agent/conversations").status_code != 403


def test_company_pause_and_resume_are_for_admins_even_with_every_section(client: TestClient) -> None:
    with _as(Access(role="member", sections=frozenset(SECTION_KEYS))):
        for path in ("/api/v1/company/pause", "/api/v1/company/resume"):
            assert client.post(path, headers=CSRF).status_code == 403, path


def _hit(kind: HitKind) -> SearchHit:
    return SearchHit(kind=kind, id=UUID(int=7), title=kind.value, subtitle=None)


def _search_kinds(client: TestClient, access: Access) -> list[str]:
    with patch("app.api.v1.search.global_search", return_value=[_hit(k) for k in HitKind]), _as(access):
        return [h["kind"] for h in client.get("/api/v1/search", params={"q": "jansen"}).json()["hits"]]


def test_search_hides_the_kinds_of_record_the_profile_cannot_open(client: TestClient) -> None:
    assert _search_kinds(client, Access(role="member", sections=frozenset({"tenants"}))) == ["person", "unit"]
    assert _search_kinds(client, Access(role="member", sections=frozenset({"maintenance"}))) == ["case"]
    assert _search_kinds(client, Access(role="owner")) == ["person", "unit", "case", "document"]

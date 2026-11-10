"""Team profiles against real Postgres: who may manage them, what each profile may open, and that a change applies on
the person's very next request."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.api.v1.sections import SECTIONS
from app.contracts import Channel
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import AllowedUser, ChannelIdentity, Company, Person
from tests.integration.access_support import CSRF, add_person_to_team, build_app, signed_in
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
PROFILES = "/api/v1/admin/profiles"
ALL_KEYS = [s.key for s in SECTIONS]
SINCE = date(2026, 1, 1)


@dataclass
class Team:
    app: FastAPI
    settings: Settings
    engine: Engine
    company: Company
    boss: Principal
    clerk: Principal
    outsider: Principal  # a superadmin of another company


@pytest.fixture
def team(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Team]:
    tag = uuid4().hex[:6]
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other BV")
        s.add(other)
        s.commit()
    cid = committed_company.id
    boss = add_person_to_team(migrated_engine, cid, f"boss-{tag}@t.test", role="superadmin")
    clerk = add_person_to_team(migrated_engine, cid, f"clerk-{tag}@t.test", role="member", sections=["contacts"])
    outsider = add_person_to_team(migrated_engine, other.id, f"out-{tag}@o.test", role="superadmin")
    app, settings = build_app(migrated_engine, pg_url)
    yield Team(app, settings, migrated_engine, committed_company, boss, clerk, outsider)
    purge_company(migrated_engine, other.id)


def _create(client, email: str = "", **body):  # type: ignore[no-untyped-def]
    payload = {"name": "Maintenance lead", "email": email, "role": "member", "sections": ["maintenance"]} | body
    return client.post(PROFILES, json=payload, headers=CSRF)


def test_a_superadmin_creates_a_profile_with_chosen_sections(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        response = _create(client, "New.Person@Example.test", sections=["maintenance", "contacts", "maintenance"])
    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["email"], body["role"]) == ("Maintenance lead", "new.person@example.test", "member")
    assert body["sections"] == ["contacts", "maintenance"]  # catalogue order, no duplicates
    assert body["is_active"] is True
    assert body["invited_by"] == team.boss.email


def test_the_listing_shows_every_profile_of_the_company_and_none_of_another(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        profiles = client.get(PROFILES).json()
    assert {p["email"] for p in profiles} == {team.boss.email, team.clerk.email}
    by_email = {p["email"]: p for p in profiles}
    assert by_email[team.boss.email]["sections"] == ALL_KEYS
    assert by_email[team.clerk.email]["sections"] == ["contacts"]


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"sections": []}, 422),
        ({"sections": ["maintenance", "payroll"]}, 422),
        ({"email": "not-an-email"}, 422),
        ({"email": "+31612345678"}, 422),
        ({"name": "   "}, 422),
        ({"role": "root"}, 422),
    ],
)
def test_invalid_profiles_are_refused(team: Team, body: dict[str, object], status: int) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        assert _create(client, **({"email": "ok@example.test"} | body)).status_code == status


def test_a_superadmin_profile_needs_no_section_list(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        response = _create(client, "second.boss@example.test", role="superadmin", sections=[])
    assert response.status_code == 201
    assert response.json()["sections"] == ALL_KEYS


def test_an_email_that_already_has_a_profile_in_this_company_is_a_409(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        assert _create(client, team.clerk.email).status_code == 409
        assert _create(client, team.clerk.email.upper()).status_code == 409


def test_an_address_another_company_uses_is_not_revealed_by_a_409(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        assert _create(client, team.outsider.email).status_code == 201


def test_the_same_address_in_two_companies_is_two_profiles(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        _create(client, team.outsider.email)
    with Session(team.engine) as s:
        rows = s.scalars(select(AllowedUser).where(AllowedUser.email == team.outsider.email)).all()
    assert {r.company_id for r in rows} == {team.company.id, team.outsider.company_id}


def test_a_member_cannot_read_or_change_profiles(team: Team) -> None:
    with signed_in(team.app, team.settings, team.clerk) as client:
        assert client.get(PROFILES).status_code == 403
        assert _create(client, "x@example.test").status_code == 403
        assert client.get("/api/v1/admin/sections").status_code == 403


def test_editing_sections_applies_on_the_next_request(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as boss, signed_in(team.app, team.settings, team.clerk) as clerk:
        assert clerk.get("/api/tenants").status_code == 403
        clerk_id = next(p["id"] for p in boss.get(PROFILES).json() if p["email"] == team.clerk.email)
        response = boss.patch(f"{PROFILES}/{clerk_id}", json={"sections": ["tenants", "contacts"]}, headers=CSRF)
        assert response.status_code == 200
        assert response.json()["sections"] == ["tenants", "contacts"]
        assert clerk.get("/api/tenants").status_code == 200
        assert clerk.get("/api/properties").status_code == 403


def test_switching_a_profile_off_ends_its_session_at_once(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as boss, signed_in(team.app, team.settings, team.clerk) as clerk:
        assert clerk.get("/api/contacts").status_code == 200
        clerk_id = next(p["id"] for p in boss.get(PROFILES).json() if p["email"] == team.clerk.email)
        assert boss.patch(f"{PROFILES}/{clerk_id}", json={"is_active": False}, headers=CSRF).status_code == 200
        assert clerk.get("/api/contacts").status_code == 401
        assert clerk.get("/api/auth/me").json()["authenticated"] is False


def test_a_superadmin_cannot_switch_off_or_demote_themselves(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as boss:
        boss_id = next(p["id"] for p in boss.get(PROFILES).json() if p["email"] == team.boss.email)
        assert boss.patch(f"{PROFILES}/{boss_id}", json={"is_active": False}, headers=CSRF).status_code == 409
        demote = {"role": "member", "sections": ["contacts"]}
        assert boss.patch(f"{PROFILES}/{boss_id}", json=demote, headers=CSRF).status_code == 409


def test_another_companys_profile_is_not_found_not_forbidden(team: Team) -> None:
    with signed_in(team.app, team.settings, team.outsider) as outsider:
        outsider_id = outsider.get(PROFILES).json()[0]["id"]
    with signed_in(team.app, team.settings, team.boss) as boss:
        response = boss.patch(f"{PROFILES}/{outsider_id}", json={"is_active": False}, headers=CSRF)
    assert response.status_code == 404


def test_me_reports_the_sections_the_profile_may_open(team: Team) -> None:
    with signed_in(team.app, team.settings, team.clerk) as client:
        me = client.get("/api/auth/me").json()
    assert (me["sections"], me["is_admin"], me["role"]) == (["contacts"], False, "member")
    with signed_in(team.app, team.settings, team.boss) as client:
        me = client.get("/api/auth/me").json()
    assert (me["sections"], me["is_admin"]) == (ALL_KEYS, True)


def test_each_section_guards_its_own_data_and_reports_may_read_the_report_data(team: Team) -> None:
    reporter = add_person_to_team(
        team.engine, team.company.id, f"rep-{uuid4().hex[:6]}@t.test", role="member", sections=["reports"]
    )
    with signed_in(team.app, team.settings, reporter) as client:
        assert client.get("/api/tenants").status_code == 200
        assert client.get("/api/properties").status_code == 200
        assert client.get("/api/maintenance/tickets").status_code == 200
        assert client.get("/api/contacts").status_code == 403
        assert client.get("/api/inbox/threads").status_code == 403
        assert client.get("/api/v1/finance/quotes").status_code == 403


def _id_of(client, email: str) -> str:  # type: ignore[no-untyped-def]
    return next(p["id"] for p in client.get(PROFILES).json() if p["email"] == email)


def test_a_member_whose_whitelist_row_was_removed_is_signed_out(team: Team) -> None:
    with signed_in(team.app, team.settings, team.clerk) as clerk:
        assert clerk.get("/api/contacts").status_code == 200
        with Session(team.engine) as s, s.begin():
            s.execute(delete(AllowedUser).where(AllowedUser.email == team.clerk.email))
        assert clerk.get("/api/contacts").status_code == 401
        assert clerk.get(PROFILES).status_code == 401


def test_a_company_without_any_whitelist_rows_keeps_full_access(migrated_engine: Engine, pg_url: str) -> None:
    from app.db.models import OwnerAccount

    with Session(migrated_engine, expire_on_commit=False) as s:
        company = Company(name="Legacy BV")
        s.add(company)
        s.commit()
    try:
        with Session(migrated_engine) as s, s.begin():
            owner = OwnerAccount(
                company_id=company.id, display_name="Old owner", whatsapp_e164="+31600000001", email="old@legacy.test"
            )
            s.add(owner)
            s.flush()
            principal = Principal(company_id=company.id, owner_id=owner.id, email="old@legacy.test")
        app, settings = build_app(migrated_engine, pg_url)
        with signed_in(app, settings, principal) as client:
            assert client.get("/api/contacts").status_code == 200
    finally:
        purge_company(migrated_engine, company.id)


def test_only_the_owner_can_change_the_owners_profile(team: Team) -> None:
    owner = add_person_to_team(team.engine, team.company.id, f"owner-{uuid4().hex[:6]}@t.test", role="owner")
    with signed_in(team.app, team.settings, team.boss) as boss:
        owner_id = _id_of(boss, owner.email)
        refused = boss.patch(f"{PROFILES}/{owner_id}", json={"is_active": False}, headers=CSRF)
        assert refused.status_code == 403
        assert "owner" in refused.json()["detail"]
        assert boss.patch(f"{PROFILES}/{owner_id}", json={"name": "Renamed"}, headers=CSRF).status_code == 403
    with signed_in(team.app, team.settings, owner) as client:
        boss_id = _id_of(client, team.boss.email)
        assert client.patch(f"{PROFILES}/{boss_id}", json={"name": "Boss"}, headers=CSRF).status_code == 200


def test_sections_alone_cannot_be_set_on_a_superadmin(team: Team) -> None:
    second = add_person_to_team(team.engine, team.company.id, f"second-{uuid4().hex[:6]}@t.test", role="superadmin")
    with signed_in(team.app, team.settings, team.boss) as boss:
        response = boss.patch(f"{PROFILES}/{_id_of(boss, second.email)}", json={"sections": ["contacts"]}, headers=CSRF)
    assert response.status_code == 422


def test_a_demoted_superadmin_loses_admin_rights_at_once(team: Team) -> None:
    """A superadmin demoted by the other cannot demote them back: the profile is re-read on every request,
    so the company keeps its admin. (The row lock for truly simultaneous edits is not exercised here.)"""
    second = add_person_to_team(team.engine, team.company.id, f"second-{uuid4().hex[:6]}@t.test", role="superadmin")
    with signed_in(team.app, team.settings, team.boss) as boss:
        second_id = _id_of(boss, second.email)
        boss_id = _id_of(boss, team.boss.email)
        demote = {"role": "member", "sections": ["contacts"]}
        assert boss.patch(f"{PROFILES}/{second_id}", json=demote, headers=CSRF).status_code == 200
    with signed_in(team.app, team.settings, second) as stale:
        assert stale.patch(f"{PROFILES}/{boss_id}", json=demote, headers=CSRF).status_code in {401, 403}
    with Session(team.engine) as s:
        admins = s.scalars(
            select(AllowedUser).where(AllowedUser.company_id == team.company.id, AllowedUser.role == "superadmin")
        ).all()
    assert [a.email for a in admins] == [team.boss.email]


def test_pause_and_resume_need_an_admin(team: Team) -> None:
    with signed_in(team.app, team.settings, team.clerk) as clerk:
        assert clerk.post("/api/v1/company/pause", headers=CSRF).status_code == 403
    with signed_in(team.app, team.settings, team.boss) as boss:
        assert boss.post("/api/v1/company/pause", headers=CSRF).status_code == 200
        assert boss.post("/api/v1/company/resume", headers=CSRF).status_code == 200


def test_the_migration_promotes_the_earliest_entry_of_a_company_with_no_admin(team: Team) -> None:
    import importlib

    migration = importlib.import_module("app.db.alembic.versions.0039_allowed_users_sections")
    with Session(team.engine, expire_on_commit=False) as s:
        orphan = Company(name="No Admin BV")
        s.add(orphan)
        s.commit()
    try:
        with Session(team.engine) as s, s.begin():
            for n, created in enumerate(("2026-01-01", "2026-02-01")):
                s.add(
                    AllowedUser(
                        company_id=orphan.id,
                        email=f"user{n}-{uuid4().hex[:6]}@o.test",
                        display_name=f"User {n}",
                        role="manager",
                        created_at=created,
                    )
                )
            s.execute(text(migration.PROMOTE_FIRST_ADMIN))
        with Session(team.engine) as s:
            roles = [
                r.role
                for r in s.scalars(
                    select(AllowedUser).where(AllowedUser.company_id == orphan.id).order_by(AllowedUser.created_at)
                )
            ]
            boss_roles = [
                r.role for r in s.scalars(select(AllowedUser).where(AllowedUser.company_id == team.company.id))
            ]
        assert roles == ["superadmin", "manager"]
        assert sorted(boss_roles) == ["member", "superadmin"]  # a company that already has an admin is left alone
    finally:
        purge_company(team.engine, orphan.id)


def _seed_tenant(engine: Engine, company_id: UUID) -> None:
    with Session(engine) as s, s.begin():
        person = Person(company_id=company_id, kind=PersonKind.tenant, display_name="Anouk de Vries", valid_from=SINCE)
        s.add(person)
        s.flush()
        for channel, identity in ((Channel.gmail, "anouk@mail.test"), (Channel.whatsapp, "+31611111111")):
            s.add(
                ChannelIdentity(
                    company_id=company_id, person_id=person.id, channel=channel, identity=identity, valid_from=SINCE
                )
            )


def test_reports_and_dashboard_see_the_rent_roll_but_not_tenant_contact_details(team: Team) -> None:
    _seed_tenant(team.engine, team.company.id)
    for section in ("reports", "dashboard"):
        reader = add_person_to_team(
            team.engine, team.company.id, f"{section}-{uuid4().hex[:6]}@t.test", role="member", sections=[section]
        )
        with signed_in(team.app, team.settings, reader) as client:
            tenants = client.get("/api/tenants").json()["tenants"]
            assert [t["name"] for t in tenants] == ["Anouk de Vries"], section
            assert (tenants[0]["phone"], tenants[0]["email"]) == ("", ""), section
            detail = client.get(f"/api/tenants/{tenants[0]['id']}").json()
            assert (detail["phone"], detail["email"]) == ("", ""), section
    holder = add_person_to_team(
        team.engine, team.company.id, f"tenants-{uuid4().hex[:6]}@t.test", role="member", sections=["tenants"]
    )
    with signed_in(team.app, team.settings, holder) as client:
        tenant = client.get("/api/tenants").json()["tenants"][0]
    assert (tenant["phone"], tenant["email"]) == ("+31611111111", "anouk@mail.test")


def test_reports_reads_the_logs_only_and_dashboard_never_reads_the_v1_inbox_or_ticket_history(team: Team) -> None:
    reporter = add_person_to_team(
        team.engine, team.company.id, f"rep-{uuid4().hex[:6]}@t.test", role="member", sections=["reports"]
    )
    with signed_in(team.app, team.settings, reporter) as client:
        assert client.get("/api/dashboard/logs").status_code == 200
        for path in ("/api/dashboard/pulse", "/api/dashboard/radar", "/api/dashboard/briefing"):
            assert client.get(path).status_code == 403, path
        assert client.get("/api/maintenance/tickets/00000000-0000-0000-0000-000000000001/history").status_code == 403
    watcher = add_person_to_team(
        team.engine, team.company.id, f"dash-{uuid4().hex[:6]}@t.test", role="member", sections=["dashboard"]
    )
    with signed_in(team.app, team.settings, watcher) as client:
        assert client.get("/api/dashboard/pulse").status_code == 200
        assert client.get("/api/inbox/threads").status_code == 200
        for path in ("/api/v1/inbox", "/api/v1/cases", "/api/v1/activity"):
            assert client.get(path).status_code == 403, path


def test_a_reports_or_dashboard_profile_gets_no_card_text_from_the_feed_or_the_calendar_writes(team: Team) -> None:
    from app.db.enums import FeedKind
    from app.db.models import OwnerFeed

    with Session(team.engine) as s, s.begin():
        s.add(
            OwnerFeed(
                company_id=team.company.id,
                idempotency_key=f"test-{uuid4().hex}",
                kind=FeedKind.approval,
                payload={"text": "Draft 1: Dear Anouk, 0611111111"},
            )
        )
    for section in ("reports", "dashboard"):
        reader = add_person_to_team(
            team.engine, team.company.id, f"{section}-{uuid4().hex[:6]}@t.test", role="member", sections=[section]
        )
        with signed_in(team.app, team.settings, reader) as client:
            cards = client.get("/api/v1/feed").json()
            assert cards, section
            assert all(c["payload"] == {} for c in cards), section
    desk = add_person_to_team(
        team.engine, team.company.id, f"inbox-{uuid4().hex[:6]}@t.test", role="member", sections=["inbox"]
    )
    with signed_in(team.app, team.settings, desk) as client:
        assert any("Dear Anouk" in c["payload"].get("text", "") for c in client.get("/api/v1/feed").json())

    watcher = add_person_to_team(
        team.engine, team.company.id, f"cal-{uuid4().hex[:6]}@t.test", role="member", sections=["dashboard"]
    )
    event = {"title": "Visit", "startTime": "2026-12-01T09:00:00Z", "endTime": "2026-12-01T10:00:00Z"}
    with signed_in(team.app, team.settings, watcher) as client:
        assert client.get("/api/calendar/events").status_code == 200
        assert client.post("/api/calendar/events", json=event, headers=CSRF).status_code == 403
        approve = client.post("/api/calendar/events/00000000-0000-0000-0000-000000000001/approve", headers=CSRF)
        assert approve.status_code == 403
        assert client.get("/api/inbox/attachments/00000000-0000-0000-0000-000000000001").status_code == 403

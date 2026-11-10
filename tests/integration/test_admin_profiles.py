"""Team profiles against real Postgres: who may manage them, what each profile may open, and that a change applies on
the person's very next request."""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.api.v1.sections import SECTIONS
from app.core.settings import Settings
from app.db.models import AllowedUser, Company
from tests.integration.access_support import CSRF, add_person_to_team, build_app, signed_in
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
PROFILES = "/api/v1/admin/profiles"
ALL_KEYS = [s.key for s in SECTIONS]


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


def test_an_email_that_already_has_a_profile_is_a_409_even_in_another_company(team: Team) -> None:
    with signed_in(team.app, team.settings, team.boss) as client:
        assert _create(client, team.clerk.email).status_code == 409
        assert _create(client, team.outsider.email.upper()).status_code == 409


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

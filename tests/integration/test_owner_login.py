"""The Google owner login: bound to the browser that started it, verified email, the whitelist's own company, and a
newly whitelisted person never takes over an existing owner."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.api.auth.login_routes import GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL
from app.api.v1.auth import COOKIE, read_session
from app.core.settings import Settings
from app.db.models import AllowedUser, Company, OwnerAccount
from app.main import create_app
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
FRONTEND = "https://dash.estateos.test"


@dataclass
class Login:
    client: TestClient
    engine: Engine
    settings: Settings
    first_company: UUID  # created first: the old code put every login here
    second_company: UUID
    harjot_id: UUID
    tag: str


def _owner_rows(engine: Engine, company_id: UUID) -> list[tuple[str | None, str]]:
    with Session(engine) as s:
        rows = s.execute(
            select(OwnerAccount.email, OwnerAccount.display_name)
            .where(OwnerAccount.company_id == company_id)
            .order_by(OwnerAccount.created_at)
        ).all()
    return [(email, name) for email, name in rows]


@pytest.fixture
def login(migrated_engine: Engine, pg_url: str) -> Iterator[Login]:
    tag = uuid4().hex[:6]
    with Session(migrated_engine) as s:
        a, b = Company(name="Login A"), Company(name="Login B")
        s.add_all([a, b])
        s.flush()
        harjot = OwnerAccount(
            company_id=a.id, display_name="Harjot", whatsapp_e164=f"+31611{uuid4().int % 10**6:06d}",
            email=f"harjot-{tag}@a.test",
        )  # fmt: skip
        s.add(harjot)
        s.add_all(
            [
                AllowedUser(company_id=b.id, email=f"newbie-{tag}@b.test", display_name="Newbie", role="manager"),
                AllowedUser(company_id=a.id, email=f"harjot-{tag}@a.test", display_name="Harjot", role="owner"),
                AllowedUser(company_id=b.id, email=f"off-{tag}@b.test", display_name="Off", is_active=False),
            ]
        )
        s.commit()
        ids = (a.id, b.id, harjot.id)
    settings = Settings(  # type: ignore[call-arg]
        database_url=pg_url, env="test", dashboard_session_secret=SecretStr("l" * 32),
        google_oauth_client_id="client-id", google_oauth_client_secret=SecretStr("client-secret"),
        frontend_base_url=FRONTEND, _env_file=None,
    )  # fmt: skip
    app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock())
    with TestClient(app, follow_redirects=False) as client:
        yield Login(client, migrated_engine, settings, ids[0], ids[1], ids[2], tag)
    for company_id in ids[:2]:
        purge_company(migrated_engine, company_id)


def _start(login: Login) -> str:
    """Begins the login the way the SPA does and returns the `state` Google would echo back."""
    url = login.client.get("/api/auth/login/google/url").json()["url"]
    return parse_qs(urlparse(url).query)["state"][0]


def _google(email: str, *, verified: bool = True, name: str = "Some Name") -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)
    router.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))
    router.get(GOOGLE_USERINFO_URL).mock(
        return_value=httpx.Response(200, json={"email": email, "email_verified": verified, "name": name})
    )
    return router


def _callback(login: Login, state: str) -> httpx.Response:
    return login.client.get(f"/api/auth/login/google/callback?code=abc&state={state}")


def test_the_authorization_url_uses_the_configured_redirect_and_sets_the_binding_cookie(login: Login) -> None:
    response = login.client.get("/api/auth/login/google/url")
    query = parse_qs(urlparse(response.json()["url"]).query)
    assert query["redirect_uri"] == [login.settings.google_login_redirect_uri]
    assert query["state"][0] == login.client.cookies.get("eo_login_state")
    assert "httponly" in response.headers["set-cookie"].lower()


@pytest.mark.parametrize("how", ["no_cookie", "wrong_state", "forged"])
def test_a_callback_not_bound_to_this_browser_is_refused_before_google_is_called(login: Login, how: str) -> None:
    state = _start(login)
    if how == "no_cookie":
        login.client.cookies.clear()
    elif how == "wrong_state":
        state = state[:-3] + "xyz"
    else:
        state = "forged"
    with respx.mock(assert_all_called=False) as router:
        token = router.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(200, json={}))
        response = _callback(login, state)
    assert response.status_code == 307
    assert response.headers["location"] == f"{FRONTEND}/login?error=invalid_state"
    assert not token.called
    assert COOKIE not in response.headers.get("set-cookie", "")


def test_a_whitelisted_person_enters_the_company_their_whitelist_row_names(login: Login) -> None:
    tag = login.tag
    state = _start(login)
    with _google(f"newbie-{tag}@b.test", name="New Person"):
        response = _callback(login, state)
    assert response.status_code == 303
    assert response.headers["location"] == f"{FRONTEND}/"
    token = login.client.cookies.get(COOKIE)
    assert token is not None
    from datetime import UTC, datetime

    principal = read_session(login.settings, token, datetime.now(UTC))
    assert principal.company_id == login.second_company  # not "the first company"
    assert _owner_rows(login.engine, login.second_company) == [(f"newbie-{tag}@b.test", "New Person")]


def test_a_newly_whitelisted_person_never_takes_over_an_existing_owner(login: Login) -> None:
    tag = login.tag
    before = _owner_rows(login.engine, login.first_company)
    state = _start(login)
    with _google(f"newbie-{tag}@b.test"):
        _callback(login, state)
    assert _owner_rows(login.engine, login.first_company) == before  # Harjot's row is untouched
    with Session(login.engine) as s:
        assert s.scalar(select(func.count()).select_from(OwnerAccount).where(OwnerAccount.id == login.harjot_id)) == 1


def test_a_second_login_reuses_the_same_owner_row(login: Login) -> None:
    tag = login.tag
    for _ in range(2):
        state = _start(login)
        with _google(f"newbie-{tag}@b.test"):
            assert _callback(login, state).status_code == 303
    assert len(_owner_rows(login.engine, login.second_company)) == 1


@pytest.mark.parametrize(
    ("email", "verified", "error"),
    [
        ("stranger@x.test", True, "access_denied"),
        ("{off}", True, "access_denied"),
        ("{newbie}", False, "unverified_email"),
    ],
)
def test_unlisted_inactive_or_unverified_emails_get_no_session_and_no_owner(
    login: Login, email: str, verified: bool, error: str
) -> None:
    tag = login.tag
    email = email.format(off=f"off-{tag}@b.test", newbie=f"newbie-{tag}@b.test")
    state = _start(login)
    with _google(email, verified=verified):
        response = _callback(login, state)
    assert response.headers["location"] == f"{FRONTEND}/login?error={error}"
    assert login.client.cookies.get(COOKIE) is None
    assert _owner_rows(login.engine, login.second_company) == []


def test_me_reports_the_same_session_the_guard_accepts_and_not_a_removed_owner(login: Login) -> None:
    tag = login.tag
    state = _start(login)
    with _google(f"newbie-{tag}@b.test"):
        _callback(login, state)
    assert login.client.get("/api/auth/me").json()["authenticated"] is True
    with Session(login.engine) as s:
        s.query(OwnerAccount).filter(OwnerAccount.company_id == login.second_company).delete()
        s.commit()
    assert login.client.get("/api/auth/me").json() == {
        "authenticated": False, "email": None, "name": None, "role": None, "company_id": None,
        "sections": [], "is_admin": False,
    }  # fmt: skip


def test_me_names_a_signed_in_owner_without_a_whitelist_row_by_their_google_name(login: Login) -> None:
    tag = login.tag
    state = _start(login)
    with _google(f"newbie-{tag}@b.test", name="Real Google Name"):
        _callback(login, state)
    with Session(login.engine) as s:  # a company with no whitelist rows at all (the Google ID-token owner)
        s.query(AllowedUser).filter(AllowedUser.company_id == login.second_company).delete()
        s.commit()
    body = login.client.get("/api/auth/me").json()
    assert body["authenticated"] is True
    assert body["name"] == "Real Google Name"  # not the email prefix "Newbie-xxxx"


def test_me_ends_the_session_of_a_person_removed_from_a_company_that_still_has_a_whitelist(login: Login) -> None:
    tag = login.tag
    state = _start(login)
    with _google(f"newbie-{tag}@b.test", name="Real Google Name"):
        _callback(login, state)
    with Session(login.engine) as s:
        s.query(AllowedUser).filter(AllowedUser.email == f"newbie-{tag}@b.test").delete()
        s.commit()
    assert login.client.get("/api/auth/me").json()["authenticated"] is False

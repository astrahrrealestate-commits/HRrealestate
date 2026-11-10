"""Shared setup for the profile-access tests: a company with signed-in people of different roles."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.core.settings import Settings
from app.db.models import AllowedUser, OwnerAccount
from app.main import create_app

CSRF = {"X-EstateOS-Client": "dashboard"}


def make_settings(pg_url: str) -> Settings:
    return Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )


def add_person_to_team(
    engine: Engine,
    company_id: UUID,
    email: str,
    *,
    role: str,
    sections: list[str] | None = None,
    is_active: bool = True,
) -> Principal:
    """A whitelist entry plus the owner row the session is bound to, as the Google login would leave them."""
    with Session(engine) as session, session.begin():
        owner = OwnerAccount(
            company_id=company_id, display_name=email, whatsapp_e164=f"web:{uuid4().hex[:12]}", email=email
        )
        session.add(owner)
        session.add(
            AllowedUser(
                company_id=company_id,
                email=email,
                display_name=email.split("@")[0].title(),
                role=role,
                sections=sections,
                is_active=is_active,
            )
        )
        session.flush()
        return Principal(company_id=company_id, owner_id=owner.id, email=email)


def build_app(engine: Engine, pg_url: str) -> tuple[FastAPI, Settings]:
    settings = make_settings(pg_url)
    return create_app(settings, engine=engine, workflow_client=MagicMock()), settings


@contextmanager
def signed_in(app: FastAPI, settings: Settings, principal: Principal) -> Iterator[TestClient]:
    with TestClient(app) as client:
        client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield client

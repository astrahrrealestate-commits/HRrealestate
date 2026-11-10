"""`connect_mailbox` changes only the company and owner named by the verified state (real Postgres)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.auth.google_routes import connect_mailbox
from app.api.auth.oauth_state import ConnectState
from app.contracts import Channel
from app.db.models import ChannelAccount, Company, OwnerAccount
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration


def _tenant(engine: Engine, name: str, email: str, mailbox: str) -> tuple[uuid.UUID, uuid.UUID]:
    with Session(engine, expire_on_commit=False) as s:
        company = Company(name=name)
        s.add(company)
        s.flush()
        owner = OwnerAccount(
            company_id=company.id,
            display_name=name,
            whatsapp_e164=f"+3160000{uuid.uuid4().int % 10000:04d}",
            email=email,
        )
        s.add_all([owner, ChannelAccount(company_id=company.id, channel=Channel.gmail, address=mailbox)])
        s.commit()
        return company.id, owner.id


@pytest.fixture
def tenants(migrated_engine: Engine) -> Iterator[dict[str, tuple[uuid.UUID, uuid.UUID]]]:
    token = uuid.uuid4().hex[:8]
    a = _tenant(migrated_engine, "Tenant A", f"a-{token}@a.test", f"mail-a-{token}@a.test")
    b = _tenant(migrated_engine, "Tenant B", f"b-{token}@b.test", f"mail-b-{token}@b.test")
    yield {"a": a, "b": b, "token": token}  # type: ignore[dict-item]
    for company_id, _ in (a, b):
        purge_company(migrated_engine, company_id)


def _rows(engine: Engine, company_id: uuid.UUID, owner_id: uuid.UUID) -> tuple[str, str | None]:
    with Session(engine) as s:
        mailbox = s.scalar(
            select(ChannelAccount.address).where(
                ChannelAccount.company_id == company_id, ChannelAccount.channel == Channel.gmail
            )
        )
        email = s.scalar(select(OwnerAccount.email).where(OwnerAccount.id == owner_id))
    assert mailbox is not None
    return mailbox, email


def test_connecting_changes_only_the_named_company_and_owner(
    migrated_engine: Engine, tenants: dict[str, tuple[uuid.UUID, uuid.UUID]]
) -> None:
    token = tenants["token"]  # type: ignore[assignment]
    (a_company, a_owner), (b_company, b_owner) = tenants["a"], tenants["b"]
    before_b = _rows(migrated_engine, b_company, b_owner)

    connect_mailbox(migrated_engine, ConnectState(a_company, a_owner, "/"), f"new-{token}@gmail.test", "New Name")

    assert _rows(migrated_engine, a_company, a_owner) == (f"new-{token}@gmail.test", f"new-{token}@gmail.test")
    assert _rows(migrated_engine, b_company, b_owner) == before_b


def test_an_owner_of_another_company_in_the_state_changes_nothing_for_that_owner(
    migrated_engine: Engine, tenants: dict[str, tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """A state naming company A but owner B must not rewrite B's login email."""
    token = tenants["token"]  # type: ignore[assignment]
    (a_company, _), (b_company, b_owner) = tenants["a"], tenants["b"]
    before_b = _rows(migrated_engine, b_company, b_owner)

    connect_mailbox(migrated_engine, ConnectState(a_company, b_owner, "/"), f"mixed-{token}@gmail.test", None)

    assert _rows(migrated_engine, b_company, b_owner) == before_b

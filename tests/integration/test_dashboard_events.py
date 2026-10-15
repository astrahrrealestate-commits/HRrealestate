"""Feed endpoint against real Postgres (company scoping, cursor paging, limit clamp, bad cursor)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.core.settings import Settings
from app.db.enums import FeedKind
from app.db.models import Company, OwnerAccount
from app.db.models.dashboard import OwnerFeed
from app.main import create_app

pytestmark = pytest.mark.integration
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _settings(url: str) -> Settings:
    return Settings(  # type: ignore[call-arg]
        database_url=url, env="test", dashboard_session_secret=SecretStr("x" * 32), _env_file=None
    )


def _rows(company: Company, tag: str, n: int) -> list[OwnerFeed]:
    return [
        OwnerFeed(
            company_id=company.id,
            idempotency_key=f"{tag}-{i}",
            kind=FeedKind.alert,
            payload={"i": i},
            created_at=T0 + timedelta(seconds=i),
        )
        for i in range(n)
    ]


@pytest.fixture
def seeded(migrated_engine: Engine, pg_url: str) -> Iterator[tuple[TestClient, list[OwnerFeed]]]:
    """Commits real rows (the API opens its own sessions) and removes them afterwards."""
    with Session(migrated_engine) as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        s.flush()
        owner = OwnerAccount(company_id=a.id, display_name="H", whatsapp_e164="+31699999999", email="h@a.test")
        a_rows = _rows(a, f"a-{a.id}", 3)
        s.add_all([owner, *a_rows, *_rows(b, f"b-{b.id}", 1)])
        s.commit()
        principal = Principal(company_id=a.id, owner_id=owner.id, email="h@a.test")
        settings = _settings(pg_url)
        app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock())
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            yield client, a_rows
        for table_rows in (s.query(OwnerFeed).filter(OwnerFeed.company_id.in_([a.id, b.id])),):
            table_rows.delete(synchronize_session=False)
        s.query(OwnerAccount).filter(OwnerAccount.id == owner.id).delete()
        s.query(Company).filter(Company.id.in_([a.id, b.id])).delete()
        s.commit()


def test_feed_returns_only_own_company_oldest_first(seeded: tuple[TestClient, list[OwnerFeed]]) -> None:
    client, rows = seeded
    body = client.get("/api/v1/feed").json()
    assert [x["id"] for x in body] == [str(r.id) for r in rows]


def test_after_cursor_returns_later_rows(seeded: tuple[TestClient, list[OwnerFeed]]) -> None:
    client, rows = seeded
    cursor = f"{rows[0].created_at.isoformat()}|{rows[0].id}"
    body = client.get("/api/v1/feed", params={"after": cursor}).json()
    assert [x["id"] for x in body] == [str(r.id) for r in rows[1:]]


def test_limit_is_clamped_to_100(migrated_engine: Engine, seeded: tuple[TestClient, list[OwnerFeed]]) -> None:
    client, rows = seeded
    with Session(migrated_engine) as s:
        company = s.get(OwnerFeed, rows[0].id)
        assert company is not None
        s.add_all(
            OwnerFeed(
                company_id=company.company_id,
                idempotency_key=f"bulk-{company.company_id}-{i}",
                kind=FeedKind.alert,
                payload={},
                created_at=T0 + timedelta(minutes=1, seconds=i),
            )
            for i in range(110)
        )
        s.commit()
    assert len(client.get("/api/v1/feed", params={"limit": 500}).json()) == 100


def test_bad_cursor_is_422(seeded: tuple[TestClient, list[OwnerFeed]]) -> None:
    client, _ = seeded
    assert client.get("/api/v1/feed", params={"after": "nonsense"}).status_code == 422


def test_identical_created_at_pages_with_limit_one(
    migrated_engine: Engine, seeded: tuple[TestClient, list[OwnerFeed]]
) -> None:
    client, rows = seeded
    with Session(migrated_engine) as s:
        company_id = rows[0].company_id
        twins = [
            OwnerFeed(
                company_id=company_id,
                idempotency_key=f"twin-{company_id}-{i}",
                kind=FeedKind.alert,
                payload={},
                created_at=T0 + timedelta(days=1),
            )
            for i in range(2)
        ]
        s.add_all(twins)
        s.commit()
        expected = [str(r.id) for r in sorted(twins, key=lambda r: r.id)]
    seen: list[str] = []
    cursor = f"{(T0 + timedelta(days=1) - timedelta(seconds=1)).isoformat()}|{UUID(int=0)}"
    for _ in range(3):
        page = client.get("/api/v1/feed", params={"after": cursor, "limit": 1}).json()
        if not page:
            break
        seen.append(page[0]["id"])
        cursor = f"{page[0]['created_at']}|{page[0]['id']}"
    assert seen == expected

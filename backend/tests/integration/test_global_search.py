"""GET /api/v1/search against real Postgres: company scoping, wildcards stay literal, grouped bounded hits."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import Category, Channel, Direction, Urgency
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import AttachmentRow, Case, Company, DocumentRow, OwnerAccount, Person, Unit
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
SINCE = date(2026, 1, 1)


def _document(session: Session, company_id: UUID, title: str) -> None:
    raw = RawEvent(company_id=company_id, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
    session.add(raw)
    session.flush()
    msg = MessageRow(
        company_id=company_id,
        raw_event_id=raw.id,
        channel=Channel.gmail,
        provider_msg_id=raw.provider_msg_id,
        thread_ref="t",
        sender_identity="x@example.test",
        direction=Direction.inbound,
        sent_at=datetime(2026, 10, 6, tzinfo=UTC),
        text="t",
        meta={},
    )
    session.add(msg)
    session.flush()
    att = AttachmentRow(
        company_id=company_id,
        message_id=msg.id,
        s3_key="k",
        mime_type="application/pdf",
        filename=f"{title}.pdf",
        size_bytes=9,
        sha256="0" * 64,
    )
    session.add(att)
    session.flush()
    session.add(
        DocumentRow(
            company_id=company_id,
            attachment_id=att.id,
            doc_type="lease",
            title=title,
            file_name=f"{title}.pdf",
            confidence=0.9,
        )
    )


@pytest.fixture
def other_company(migrated_engine: Engine) -> Iterator[Company]:
    """A second company holding a match for every kind: none of it may ever show up for the first."""
    with Session(migrated_engine, expire_on_commit=False) as session:
        company = Company(name="Other BV")
        session.add(company)
        session.commit()
        session.add(
            Person(company_id=company.id, kind=PersonKind.tenant, display_name="Jansen Elsewhere", valid_from=SINCE)
        )
        session.add(Unit(company_id=company.id, label="Kerkstraat Elsewhere", valid_from=SINCE))
        session.add(
            Case(
                company_id=company.id,
                category=Category.maintenance,
                urgency=Urgency.normal,
                summary="Jansen leak elsewhere",
            )
        )
        _document(session, company.id, "Jansen lease elsewhere")
        session.commit()
    yield company
    purge_company(migrated_engine, company.id)


@pytest.fixture
def client(
    migrated_engine: Engine, pg_url: str, committed_company: Company, other_company: Company
) -> Iterator[TestClient]:
    cid = committed_company.id
    with Session(migrated_engine, expire_on_commit=False) as s:
        owner = OwnerAccount(company_id=cid, display_name="H", whatsapp_e164="+31699999977", email="h@s.test")
        s.add(owner)
        s.add(Person(company_id=cid, kind=PersonKind.tenant, display_name="Anna Jansen", valid_from=SINCE))
        s.add(
            Person(company_id=cid, kind=PersonKind.contractor, display_name="Bakker", trade="plumber", valid_from=SINCE)
        )
        s.add(
            Person(
                company_id=cid,
                kind=PersonKind.tenant,
                display_name="Jansen Moved Out",
                valid_from=date(2024, 1, 1),
                valid_to=date(2025, 12, 31),
            )
        )
        s.add(Unit(company_id=cid, label="Unit 4B", address="Kerkstraat 12, Rotterdam", valid_from=SINCE))
        s.add(
            Case(
                company_id=cid,
                category=Category.maintenance,
                urgency=Urgency.normal,
                summary="Roof leak above unit 4B, tenant Jansen asked for a plumber",
            )
        )
        _document(s, cid, "Lease Jansen 4B")
        s.commit()
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    principal = Principal(company_id=cid, owner_id=owner.id, email="h@s.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield c


def _hits(client: TestClient, q: str) -> list[dict[str, str | None]]:
    response = client.get("/api/v1/search", params={"q": q})
    assert response.status_code == 200
    hits: list[dict[str, str | None]] = response.json()["hits"]
    return hits


def test_search_groups_hits_by_kind_and_stays_in_the_company(client: TestClient) -> None:
    hits = _hits(client, "jansen")
    assert [(h["kind"], h["title"]) for h in hits] == [
        ("person", "Anna Jansen"),
        ("case", "Roof leak above unit 4B, tenant Jansen asked for a plumber"),
        ("document", "Lease Jansen 4B"),
    ]
    assert hits[0]["person_kind"] == "tenant"
    assert hits[1]["person_kind"] is None


def test_other_companys_units_and_documents_never_show(client: TestClient) -> None:
    assert [h["title"] for h in _hits(client, "kerkstraat")] == ["Unit 4B"]
    assert [h["title"] for h in _hits(client, "elsewhere")] == []


def test_people_whose_validity_has_ended_are_not_listed(client: TestClient) -> None:
    assert "Jansen Moved Out" not in {h["title"] for h in _hits(client, "jansen")}


def test_search_matches_trade_unit_label_and_address(client: TestClient) -> None:
    assert [h["title"] for h in _hits(client, "plumber") if h["kind"] == "person"] == ["Bakker"]
    assert [h["title"] for h in _hits(client, "4b") if h["kind"] == "unit"] == ["Unit 4B"]
    assert [h["title"] for h in _hits(client, "kerkstraat") if h["kind"] == "unit"] == ["Unit 4B"]
    assert [h["title"] for h in _hits(client, "lease jansen") if h["kind"] == "document"] == ["Lease Jansen 4B"]


def test_wildcards_are_literal_and_short_queries_return_nothing(client: TestClient) -> None:
    assert _hits(client, "%%") == []
    assert _hits(client, "_n") == []
    assert _hits(client, "a") == []
    assert _hits(client, "") == []


def test_a_nul_byte_in_the_query_is_dropped_not_a_500(client: TestClient) -> None:
    assert [h["title"] for h in _hits(client, "ba\x00kker")] == ["Bakker"]


def test_search_needs_a_session(migrated_engine: Engine, pg_url: str) -> None:
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as anonymous:
        assert anonymous.get("/api/v1/search", params={"q": "jansen"}).status_code == 401

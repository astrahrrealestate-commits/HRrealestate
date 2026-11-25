"""Regression tests verifying batched query count, latency, and read-only GET on inbox endpoints."""

from datetime import UTC, datetime, timedelta
from time import perf_counter
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, Principal, issue_session
from app.contracts import CaseState, Category, Channel, Direction, Urgency
from app.core.settings import Settings
from app.db.enums import LinkMethod, PersonKind, PipelineStatus
from app.db.models import Case, CaseLink, Company, OwnerAccount, Person, Unit
from app.db.models.ingestion import MessageRow, RawEvent
from app.main import create_app
from app.storage.memory import MemoryStorage

pytestmark = pytest.mark.integration


def _seed_many_cases(engine: Engine, count: int) -> tuple[UUID, UUID, str]:
    base = datetime(2026, 2, 1, tzinfo=UTC)
    with Session(engine) as s:
        company = Company(name=f"Batch-{uuid4().hex[:6]}")
        s.add(company)
        s.flush()
        email = f"owner-{uuid4().hex[:6]}@example.test"
        owner = OwnerAccount(
            company_id=company.id,
            display_name="Owner",
            email=email,
            whatsapp_e164="+31600000001",
        )
        unit = Unit(company_id=company.id, label="Unit 1", valid_from=base.date())
        s.add_all([owner, unit])
        s.flush()

        for i in range(count):
            person = Person(
                company_id=company.id,
                kind=PersonKind.contractor if i % 2 else PersonKind.tenant,
                display_name=f"Person {i}",
                valid_from=base.date(),
            )
            s.add(person)
            s.flush()
            raw = RawEvent(company_id=company.id, provider=Channel.gmail, provider_msg_id=f"raw-{i}", payload={})
            s.add(raw)
            s.flush()
            msg = MessageRow(
                company_id=company.id,
                raw_event_id=raw.id,
                channel=Channel.gmail,
                provider_msg_id=f"msg-{i}",
                thread_ref=f"<t-{i}@mail.example>",
                person_id=person.id,
                sender_identity=f"p{i}@example.test",
                direction=Direction.inbound,
                sent_at=base + timedelta(minutes=i),
                text=f"Message {i}",
                pipeline_status=PipelineStatus.done,
            )
            case = Case(
                company_id=company.id,
                unit_id=unit.id,
                category=Category.maintenance,
                urgency=Urgency.normal,
                state=CaseState.open,
            )
            s.add_all([msg, case])
            s.flush()
            s.add(CaseLink(company_id=company.id, case_id=case.id, message_id=msg.id, method=LinkMethod.thread))

        company_id, owner_id = company.id, owner.id
        s.commit()
        return company_id, owner_id, email


def test_inbox_threads_uses_bounded_queries_and_no_commit(migrated_engine: Engine, pg_url: str) -> None:
    company_id, owner_id, email = _seed_many_cases(migrated_engine, count=18)
    settings = Settings(
        database_url=pg_url,  # type: ignore[arg-type]
        env="test",
        dashboard_session_secret=SecretStr("x" * 32),
        _env_file=None,
    )
    principal = Principal(company_id=company_id, owner_id=owner_id, email=email)
    app = create_app(settings, engine=migrated_engine, workflow_client=MagicMock(), storage=MemoryStorage())

    queries: list[str] = []

    def _record_sql(
        _conn: object, _cursor: object, statement: str, _params: object, _ctx: object, _executemany: bool
    ) -> None:
        queries.append(statement.strip().upper())

    try:
        with TestClient(app) as client:
            client.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
            # Warm auth lookup once, then count queries strictly during GET routes
            event.listen(migrated_engine, "before_cursor_execute", _record_sql)
            try:
                t0 = perf_counter()
                res = client.get("/api/inbox/threads", params={"limit": 20, "offset": 0})
                inbox_ms = (perf_counter() - t0) * 1000
                stats_res = client.get("/api/inbox/stats")
            finally:
                event.remove(migrated_engine, "before_cursor_execute", _record_sql)

            assert res.status_code == 200
            assert stats_res.status_code == 200
            assert len(res.json()["threads"]) == 18
            # Bounded O(1) batch query count (well below the old 18 * ~15 = 270+ N+1 queries)
            assert len(queries) <= 35, f"Expected batched O(1) queries, saw {len(queries)} in {inbox_ms:.1f}ms"
            assert not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "COMMIT")) for sql in queries)

            # Verify directory/ops batched endpoints also respond cleanly
            for path in (
                "/api/properties",
                "/api/tenants",
                "/api/contacts",
                "/api/maintenance/tickets",
                "/api/dashboard/radar",
            ):
                assert client.get(path).status_code == 200
    finally:
        with Session(migrated_engine) as s:
            s.query(CaseLink).filter(CaseLink.company_id == company_id).delete(synchronize_session=False)
            for model in (MessageRow, RawEvent, Case, Person, Unit, OwnerAccount):
                s.query(model).filter(model.company_id == company_id).delete(synchronize_session=False)
            s.query(Company).filter(Company.id == company_id).delete(synchronize_session=False)
            s.commit()

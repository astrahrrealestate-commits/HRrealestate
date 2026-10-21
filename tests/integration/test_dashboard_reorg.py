"""Drive reorganisation API and workflow: propose, show, decide (CSRF, scoping), enqueue by name, apply."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.core.workflow_names import DOCUMENTS_QUEUE, REORG_PLAN
from app.db.enums import DocLinkKind, DocumentStatus, PersonKind
from app.db.models import (
    AttachmentRow,
    Company,
    DocumentLink,
    DocumentRow,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
    Unit,
)
from app.main import create_app
from app.storage.drive import MemoryDrive
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
CSRF = {CSRF_HEADER: CSRF_VALUE}
OLD_NAME = "2026-10-07_lease_jan-bakker_huurovereenkomst.pdf"


@dataclass
class Fx:
    client: TestClient
    workflow_client: MagicMock
    doc: UUID
    other_doc: UUID
    unit: UUID
    engine: Engine
    drive: MemoryDrive
    company_id: UUID


def _doc(s: Session, cid: UUID, unit: Unit | None, drive: MemoryDrive) -> UUID:
    raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(uuid4()), payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
                     thread_ref="t", sender_identity="x@y.test", direction=Direction.inbound,
                     sent_at=datetime(2026, 1, 1, tzinfo=UTC), text="hi", meta={})  # fmt: skip
    s.add(msg)
    s.flush()
    att = AttachmentRow(company_id=cid, message_id=msg.id, s3_key="k", mime_type="application/pdf", filename="x.pdf",
                        size_bytes=1, sha256="0" * 64)  # fmt: skip
    s.add(att)
    s.flush()
    file_id = drive.new_file_id()
    drive.upload(file_id, drive.ensure_folder(("EstateOS", "lease", "2026")), OLD_NAME, "application/pdf", b"%", att.id)
    doc = DocumentRow(company_id=cid, attachment_id=att.id, doc_type="lease", title="Huur", file_name=OLD_NAME,
                      confidence=0.9, status=DocumentStatus.filed, drive_file_id=file_id,
                      drive_folder="EstateOS/lease/2026")  # fmt: skip
    s.add(doc)
    s.flush()
    if unit:
        s.add(DocumentLink(company_id=cid, document_id=doc.id, kind=DocLinkKind.unit, ref_id=unit.id, method="fuzzy",
                           score=0.9))  # fmt: skip
    return doc.id


@pytest.fixture
def fx(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Fx]:
    drive = MemoryDrive()
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.flush()
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999993",
                             email="h@a.test")  # fmt: skip
        unit = Unit(company_id=committed_company.id, label="Kerkstraat 12-2", valid_from=date(2025, 1, 1))
        s.add_all([owner, unit])
        s.flush()
        mine = _doc(s, committed_company.id, unit, drive)
        theirs = _doc(s, other.id, None, MemoryDrive())
        s.commit()
    settings = Settings(database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32),  # type: ignore[arg-type]
                        _env_file=None)  # fmt: skip
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    workflow_client = MagicMock()
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=workflow_client)) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield Fx(c, workflow_client, mine, theirs, unit.id, migrated_engine, drive, committed_company.id)
    purge_company(migrated_engine, other.id)


def test_no_plan_yet_is_null(fx: Fx) -> None:
    assert fx.client.get("/api/v1/documents/reorg").json() is None


def test_propose_then_show_the_plan(fx: Fx) -> None:
    assert fx.client.post("/api/v1/documents/reorg").status_code == 403  # CSRF
    made = fx.client.post("/api/v1/documents/reorg", headers=CSRF).json()
    assert made["plan_id"] is not None
    plan = fx.client.get("/api/v1/documents/reorg").json()
    assert (plan["id"], plan["status"], plan["created_by"]) == (made["plan_id"], "proposed", "owner")
    [item] = plan["items"]
    assert (item["document_id"], item["title"], item["status"]) == (str(fx.doc), "Huur", "proposed")
    assert (item["from_folder"], item["to_folder"]) == ("EstateOS/lease/2026", "EstateOS/Kerkstraat 12-2/Leases/2026")
    assert fx.client.post("/api/v1/documents/reorg", headers=CSRF).json() == {"plan_id": None}  # already planned


def test_approving_enqueues_the_apply_workflow_by_name(fx: Fx) -> None:
    plan_id = fx.client.post("/api/v1/documents/reorg", headers=CSRF).json()["plan_id"]
    url = f"/api/v1/documents/reorg/{plan_id}/decide"
    assert fx.client.post(url, json={"approve": True}).status_code == 403
    done = fx.client.post(url, json={"approve": True}, headers=CSRF)
    assert (done.status_code, done.json()) == (202, {"status": "approved"})
    options: dict[str, Any] = fx.workflow_client.enqueue.call_args.args[0]
    assert (options["queue_name"], options["workflow_name"]) == (DOCUMENTS_QUEUE, REORG_PLAN)
    assert options["workflow_id"] == f"drive:reorg:{plan_id}"
    assert options["queue_partition_key"] == str(fx.company_id)
    assert fx.client.get("/api/v1/documents/reorg").json()["items"][0]["status"] == "approved"


def test_rejecting_enqueues_nothing(fx: Fx) -> None:
    plan_id = fx.client.post("/api/v1/documents/reorg", headers=CSRF).json()["plan_id"]
    done = fx.client.post(f"/api/v1/documents/reorg/{plan_id}/decide", json={"approve": False}, headers=CSRF)
    assert done.json() == {"status": "rejected"}
    fx.workflow_client.enqueue.assert_not_called()


def test_item_ids_limit_the_approval(fx: Fx) -> None:
    plan_id = fx.client.post("/api/v1/documents/reorg", headers=CSRF).json()["plan_id"]
    url = f"/api/v1/documents/reorg/{plan_id}/decide"
    done = fx.client.post(url, json={"approve": True, "item_ids": [str(uuid4())]}, headers=CSRF)
    assert done.json() == {"status": "rejected"}  # none of the chosen ids is in the plan


def test_a_foreign_or_unknown_plan_is_404(fx: Fx, migrated_engine: Engine) -> None:
    assert (
        fx.client.post(f"/api/v1/documents/reorg/{uuid4()}/decide", json={"approve": True}, headers=CSRF).status_code
        == 404
    )
    from app.pipeline.drive_reorg import build_plan

    with Session(migrated_engine) as s:
        other_company = s.scalars(select(Company.id).where(Company.name == "Other")).one()
    foreign = build_plan(migrated_engine, other_company, "owner")
    assert foreign is not None
    resp = fx.client.post(f"/api/v1/documents/reorg/{foreign}/decide", json={"approve": True}, headers=CSRF)
    assert resp.status_code == 404
    assert fx.client.get("/api/v1/documents/reorg").json() is None  # the other company's plan is not mine


def test_changing_a_link_proposes_a_one_item_plan_and_never_moves_the_file(fx: Fx) -> None:
    with Session(fx.engine, expire_on_commit=False) as s:
        anna = Person(company_id=fx.company_id, kind=PersonKind.tenant, display_name="Anna de Vries",
                      valid_from=date(2025, 1, 1))  # fmt: skip
        s.add(anna)
        s.commit()
    resp = fx.client.post(
        f"/api/v1/documents/{fx.doc}/links", json={"kind": "person", "ref_id": str(anna.id)}, headers=CSRF
    )
    assert resp.status_code == 204
    plan = fx.client.get("/api/v1/documents/reorg").json()
    assert plan["created_by"] == "system"
    assert [i["to_name"] for i in plan["items"]] == ["2026-10-07_lease_anna-de-vries_huurovereenkomst.pdf"]
    with Session(fx.engine) as s:
        assert (
            s.scalars(select(DocumentRow.drive_folder).where(DocumentRow.id == fx.doc)).one() == "EstateOS/lease/2026"
        )


def test_the_reorg_routes_do_not_shadow_the_document_id_routes(fx: Fx) -> None:
    assert fx.client.get(f"/api/v1/documents/{fx.doc}").status_code == 200
    assert fx.client.get("/api/v1/documents/reorg").status_code == 200


def test_unauthenticated_requests_are_refused(fx: Fx) -> None:
    fx.client.cookies.clear()
    assert fx.client.get("/api/v1/documents/reorg").status_code == 401
    assert fx.client.post("/api/v1/documents/reorg", headers=CSRF).status_code == 401


def test_backfill_enqueues_once_per_day_by_name(fx: Fx) -> None:
    assert fx.client.post("/api/v1/documents/backfill").status_code == 403
    assert fx.client.post("/api/v1/documents/backfill", headers=CSRF).status_code == 202
    options: dict[str, Any] = fx.workflow_client.enqueue.call_args.args[0]
    assert options["workflow_name"] == "documents.backfill"
    assert options["workflow_id"].startswith(f"docs:backfill:{fx.company_id}:")
    assert options["queue_partition_key"] == str(fx.company_id)

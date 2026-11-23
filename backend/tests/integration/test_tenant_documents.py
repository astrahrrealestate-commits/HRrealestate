"""A tenant's BRIXX documents: what is listed, what is not, and the file behind each entry.

Synthetic rows in the migrated mirror; files are in memory storage. Every name, size and byte is invented.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.api.v1.auth import Principal
from app.core.settings import Settings
from app.db.enums import BrixxDocumentStatus, PersonKind
from app.db.models import Company, Lease, LeaseParty, Person, Unit
from app.db.models.brixx import BrixxDocument
from app.directory.brixx.tenant_documents import tenant_documents
from app.main import create_app
from app.storage.memory import MemoryStorage
from tests.api_auth import as_owner
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
TODAY = date(2026, 11, 20)
MIRROR_TABLES = (
    "prg_document",
    "prg_relatiedocument",
    "prg_document_link",
    "typ_documentcategorie",
    "typ_relatiedocument",
    "prg_subobject",
)
PDF = b"%PDF-1.4 test"


def _mirror(session: Session, table: str, company: UUID, **values: Any) -> None:
    columns = ", ".join(["company_id", *values])
    binds = ", ".join(f":{name}" for name in ["company_id", *values])
    statement = f"insert into brixx.{table} ({columns}) values ({binds})"  # noqa: S608 - test table names
    session.execute(sa.text(statement), {"company_id": company, **values})


def _doc(session: Session, company: UUID, key: int, name: str, size: int = 100, category: int | None = 1) -> None:
    _mirror(
        session,
        "prg_document",
        company,
        prg_documentid=key,
        benaming=name,
        filenaam=f"{name}.pdf",
        groottebytes=size,
        typ_documentcategorieid=category,
        newdatetime=datetime(2026, 1, key, tzinfo=UTC),
    )


def _link(session: Session, company: UUID, key: int, kind: int, entity: int, **extra: Any) -> None:
    _mirror(
        session,
        "prg_document_link",
        company,
        prg_document_linkid=key,
        prg_documentid=key,
        entiteitid=entity,
        sys_entiteittypeid=kind,
        **extra,
    )


class World:
    def __init__(
        self, client: TestClient, engine: Engine, company: UUID, tenant: UUID, other: UUID, storage: MemoryStorage
    ):
        self.client, self.engine, self.company, self.tenant, self.other, self.storage = (
            client,
            engine,
            company,
            tenant,
            other,
            storage,
        )


@pytest.fixture
def world(migrated_engine: Engine, pg_url: str) -> Iterator[World]:
    storage = MemoryStorage()
    with Session(migrated_engine) as s:
        company = Company(name="Docs BV")
        s.add(company)
        s.flush()
        cid = company.id

        def tenant(ref: str, name: str, unit_ref: str, contract: str) -> UUID:
            person = Person(company_id=cid, kind=PersonKind.tenant, display_name=name, brixx_ref=ref, valid_from=TODAY)
            unit = Unit(company_id=cid, label=f"Unit {unit_ref}", brixx_ref=unit_ref, valid_from=TODAY)
            s.add_all([person, unit])
            s.flush()
            lease = Lease(company_id=cid, unit_id=unit.id, brixx_ref=f"{contract}:1", valid_from=date(2025, 1, 1))
            s.add(lease)
            s.flush()
            s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=person.id, role="tenant"))
            return person.id

        mine, other = tenant("1", "Relatie R-00001", "100", "500"), tenant("2", "Relatie R-00002", "200", "600")
        _mirror(s, "typ_documentcategorie", cid, typ_documentcategorieid=1, benaming="Contracten")
        _mirror(s, "typ_relatiedocument", cid, typ_relatiedocumentid=7, benaming="Identiteitsbewijs")
        _mirror(s, "prg_subobject", cid, prg_subobjectid=100, prg_objectid=10)
        _mirror(s, "prg_subobject", cid, prg_subobjectid=200, prg_objectid=20)
        for key, name in (
            (1, "own"),
            (2, "contract"),
            (3, "unit"),
            (4, "building"),
            (5, "own-linked"),
            (6, "other"),
            (7, "gone"),
        ):
            _doc(s, cid, key, name, size=100 + key)
        _mirror(
            s,
            "prg_relatiedocument",
            cid,
            prg_relatiedocumentid=1,
            prg_documentid=1,
            prg_relatieid=1,
            typ_relatiedocumentid=7,
            indverwijderd=0,
        )
        _mirror(
            s,
            "prg_relatiedocument",
            cid,
            prg_relatiedocumentid=2,
            prg_documentid=6,
            prg_relatieid=2,
            typ_relatiedocumentid=7,
            indverwijderd=0,
        )
        _mirror(
            s,
            "prg_relatiedocument",
            cid,
            prg_relatiedocumentid=3,
            prg_documentid=7,
            prg_relatieid=1,
            typ_relatiedocumentid=7,
            indverwijderd=1,
        )
        _link(s, cid, 2, 9, 500)  # contract
        _link(s, cid, 3, 12, 100)  # unit
        _link(s, cid, 4, 11, 10)  # building
        _link(s, cid, 5, 10, 1)  # relatie, through the generic link
        _link(s, cid, 6, 9, 600)  # the other tenant's contract
        _link(s, cid, 7, 9, 500, _deleted_at=datetime(2026, 11, 1, tzinfo=UTC))  # removed in BRIXX
        key = f"brixx/{cid}/documents/1/{'a' * 64}"
        storage.put(key, PDF, "application/octet-stream")
        s.add(
            BrixxDocument(
                company_id=cid,
                document_id=1,
                source_version="v1",
                status=BrixxDocumentStatus.stored,
                sha256="a" * 64,
                storage_key=key,
                size_bytes=len(PDF),
            )
        )
        s.commit()
    settings = Settings(database_url=pg_url, env="test", _env_file=None)  # type: ignore[call-arg]
    owner = Principal(company_id=cid, owner_id=uuid4(), email="harjot@example.test")
    app = as_owner(create_app(settings, engine=migrated_engine, workflow_client=None, storage=storage), owner)
    with TestClient(app) as client:
        yield World(client, migrated_engine, cid, mine, other, storage)
    with Session(migrated_engine) as s:
        for table in MIRROR_TABLES:
            s.execute(sa.text(f"delete from brixx.{table} where company_id = :c"), {"c": cid})  # noqa: S608
        s.commit()
    purge_company(migrated_engine, cid)


def test_a_tenants_documents_come_from_their_relatie_contract_unit_and_building(world: World) -> None:
    with Session(world.engine) as s:
        docs = tenant_documents(s, world.company, world.tenant)
    assert docs is not None
    assert {d.title: d.source for d in docs} == {
        "own": "Tenant",
        "contract": "Contract",
        "unit": "Unit",
        "building": "Building",
        "own-linked": "Tenant",
    }  # not the other tenant's, not the one BRIXX removed or marked deleted
    by_title = {d.title: d for d in docs}
    assert by_title["own"].category == "Identiteitsbewijs"  # BRIXX's own relatie-document label wins
    assert by_title["contract"].category == "Contracten"
    assert [d.available for d in docs if d.title == "own"] == [True]
    assert not any(d.available for d in docs if d.title != "own")


def test_the_list_endpoint_shows_state_and_a_url_only_for_stored_files(world: World) -> None:
    body = world.client.get(f"/api/tenants/{world.tenant}/documents").json()
    assert (body["total"], body["available"]) == (5, 1)
    own = next(d for d in body["documents"] if d["title"] == "own")
    assert own["url"] == f"/api/tenants/{world.tenant}/documents/1/file"
    assert own["addedOn"] == "01-01-2026"
    assert next(d for d in body["documents"] if d["title"] == "unit")["url"] is None


def test_the_file_is_served_from_storage_with_safe_headers(world: World) -> None:
    response = world.client.get(f"/api/tenants/{world.tenant}/documents/1/file")
    assert (response.status_code, response.content) == (200, PDF)
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]


def test_a_document_that_is_not_downloaded_yet_is_a_409_not_a_404(world: World) -> None:
    assert world.client.get(f"/api/tenants/{world.tenant}/documents/2/file").status_code == 409


def test_another_tenants_or_unknown_document_is_not_found(world: World) -> None:
    assert world.client.get(f"/api/tenants/{world.tenant}/documents/6/file").status_code == 404  # linked to tenant 2
    assert world.client.get(f"/api/tenants/{world.tenant}/documents/7/file").status_code == 404  # removed in BRIXX
    assert world.client.get(f"/api/tenants/{world.tenant}/documents/999/file").status_code == 404
    assert world.client.get(f"/api/tenants/{world.other}/documents/1/file").status_code == 404  # not their document


def test_an_unknown_or_foreign_tenant_is_not_found(world: World) -> None:
    assert world.client.get(f"/api/tenants/{uuid4()}/documents").status_code == 404
    assert world.client.get("/api/tenants/not-a-uuid/documents").status_code == 404


def test_a_file_that_is_not_a_pdf_or_image_is_always_a_download(world: World) -> None:
    key = f"brixx/{world.company}/documents/3/{'b' * 64}"
    world.storage.put(key, b"<script>alert(1)</script>", "application/octet-stream")
    with Session(world.engine) as s:
        _mirror(
            s, "prg_document", world.company, prg_documentid=30, benaming="evil", filenaam='x".html', groottebytes=5
        )
        _link(s, world.company, 30, 12, 100)
        s.add(
            BrixxDocument(
                company_id=world.company,
                document_id=30,
                source_version="v1",
                status=BrixxDocumentStatus.stored,
                sha256="b" * 64,
                storage_key=key,
                size_bytes=5,
            )
        )
        s.commit()
    response = world.client.get(f"/api/tenants/{world.tenant}/documents/30/file")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert '"' not in response.headers["content-disposition"].split("filename*=UTF-8''")[1]

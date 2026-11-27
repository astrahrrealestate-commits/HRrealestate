"""BRIXX documents in the document library (M13): a tenant's BRIXX lease reaches their dossier and Astra's search.

Synthetic mirror rows (the tenant-documents fixtures) and files in memory storage. Every name and byte is invented.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.db.enums import BrixxDocumentStatus, DocLinkKind, DocumentStatus, ExtractionStatus, PersonKind
from app.db.models import Company, DocumentChunk, DocumentLink, DocumentRow, Lease, LeaseParty, Person, Unit
from app.db.models.brixx import BrixxDocument
from app.db.models.brixx_directory import BrixxErasedRef
from app.llm.embeddings import HashingEmbedder
from app.pipeline.dossier import build_dossier
from app.storage.extract import Extraction
from app.storage.memory import MemoryStorage
from app.workflows.brixx_library import index_backlog, index_brixx_document
from tests.integration.conversation_support import add_case, add_mail
from tests.integration.test_tenant_documents import _doc, _link, _mirror

pytestmark = pytest.mark.integration
LEASE_TEXT = "Huurovereenkomst Singel 5. Artikel 7: huisdieren alleen met schriftelijke toestemming van verhuurder."


class Reader:
    def extract(self, data: bytes, mime_type: str, filename: str | None) -> Extraction:
        text = data.decode()
        return Extraction(ExtractionStatus.done if text else ExtractionStatus.skipped, text or None, 1, "fake")


@dataclass
class World:
    company: UUID
    anouk: UUID
    bram: UUID
    storage: MemoryStorage


def _tenant(s: Session, cid: UUID, ref: str, name: str, unit_ref: str, contract: str) -> UUID:
    person = Person(
        company_id=cid, kind=PersonKind.tenant, display_name=name, brixx_ref=ref, valid_from=date(2026, 1, 1)
    )
    unit = Unit(company_id=cid, label=f"Unit {unit_ref}", brixx_ref=unit_ref, valid_from=date(2026, 1, 1))
    s.add_all([person, unit])
    s.flush()
    lease = Lease(company_id=cid, unit_id=unit.id, brixx_ref=f"{contract}:1", valid_from=date(2025, 1, 1))
    s.add(lease)
    s.flush()
    s.add(LeaseParty(company_id=cid, lease_id=lease.id, person_id=person.id, role="tenant"))
    return person.id


def _store(s: Session, storage: MemoryStorage, cid: UUID, document_id: int, data: bytes, version: str = "v1") -> UUID:
    key = f"brixx/{cid}/documents/{document_id}/{version}"
    storage.put(key, data, "application/pdf")
    row = BrixxDocument(company_id=cid, document_id=document_id, source_version=version,
                        status=BrixxDocumentStatus.stored, sha256=f"{document_id}{version}".ljust(64, "0")[:64],
                        storage_key=key, size_bytes=len(data), content_type="application/pdf")  # fmt: skip
    s.add(row)
    s.flush()
    return row.id


@pytest.fixture
def world(migrated_engine: Engine, committed_company: Company) -> World:
    cid, storage = committed_company.id, MemoryStorage()
    with Session(migrated_engine) as s, s.begin():
        anouk = _tenant(s, cid, "1", "Anouk", "100", "500")
        bram = _tenant(s, cid, "2", "Bram", "200", "600")
        from app.contracts import Channel
        from app.db.models import ChannelIdentity

        s.add(ChannelIdentity(company_id=cid, person_id=anouk, channel=Channel.gmail, identity="anouk@example.test",
                              valid_from=date(2026, 1, 1)))  # fmt: skip
        _mirror(s, "typ_documentcategorie", cid, typ_documentcategorieid=1, benaming="Contracten")
        _mirror(s, "typ_relatiedocument", cid, typ_relatiedocumentid=7, benaming="Identiteitsbewijs")
        _mirror(s, "prg_subobject", cid, prg_subobjectid=100, prg_objectid=10)
        for key, name in ((2, "Huurovereenkomst Anouk"), (6, "Huurovereenkomst Bram"), (1, "Paspoort"), (8, "Leeg")):
            _doc(s, cid, key, name)
        _link(s, cid, 2, 9, 500)  # Anouk's contract
        _link(s, cid, 6, 9, 600)  # Bram's contract
        _link(s, cid, 8, 9, 500)
        _mirror(s, "prg_relatiedocument", cid, prg_relatiedocumentid=1, prg_documentid=1, prg_relatieid=1,
                typ_relatiedocumentid=7, indverwijderd=0)  # fmt: skip
        _store(s, storage, cid, 2, LEASE_TEXT.encode())
        _store(s, storage, cid, 6, b"Huurovereenkomst Bram. Huisdieren BRAM-GEHEIM toegestaan.")
        _store(s, storage, cid, 1, b"Paspoort van Anouk, nummer NX123")
        _store(s, storage, cid, 8, b"")
    return World(cid, anouk, bram, storage)


def _index_all(engine: Engine, w: World) -> int:
    return index_backlog(engine, w.storage, Reader(), HashingEmbedder(), w.company)


def test_a_tenants_brixx_lease_is_indexed_linked_and_in_their_dossier(migrated_engine: Engine, world: World) -> None:
    assert _index_all(migrated_engine, world) == 4
    with Session(migrated_engine) as s:
        doc = s.scalars(select(DocumentRow).where(DocumentRow.title == "Huurovereenkomst Anouk")).one()
        assert (doc.doc_type, doc.status, doc.attachment_id) == ("lease", DocumentStatus.filed, None)
        kinds = {
            (link.kind, link.ref_id)
            for link in s.scalars(select(DocumentLink).where(DocumentLink.document_id == doc.id))
        }
        lease = s.scalars(select(Lease.id).join(LeaseParty).where(LeaseParty.person_id == world.anouk)).one()
        assert {(DocLinkKind.person, world.anouk), (DocLinkKind.lease, lease)} <= kinds
    case = add_case(migrated_engine, world.company, world.anouk)
    mid = add_mail(migrated_engine, world.company, "Mag ik een hond houden?", sender="anouk@example.test",
                   person_id=world.anouk, case_id=case)  # fmt: skip
    with Session(migrated_engine) as s:
        dossier = build_dossier(s, world.company, mid, HashingEmbedder())
    texts = " ".join(p.text for p in dossier.documents)
    assert "schriftelijke toestemming" in texts
    assert "BRAM-GEHEIM" not in texts


def test_identity_documents_and_empty_files_are_never_read(migrated_engine: Engine, world: World) -> None:
    _index_all(migrated_engine, world)
    with Session(migrated_engine) as s:
        rows = dict(s.execute(select(DocumentRow.title, DocumentRow.status)).all())
        chunks = " ".join(s.scalars(select(DocumentChunk.text)))
    assert rows["Paspoort"] is DocumentStatus.skipped
    assert rows["Leeg"] is DocumentStatus.skipped
    assert "NX123" not in chunks


def test_indexing_twice_indexes_once(migrated_engine: Engine, world: World) -> None:
    _index_all(migrated_engine, world)
    assert _index_all(migrated_engine, world) == 0
    with Session(migrated_engine) as s:
        assert s.scalar(select(func.count(DocumentRow.id)).where(DocumentRow.company_id == world.company)) == 4


def test_a_new_version_replaces_the_old_one(migrated_engine: Engine, world: World) -> None:
    _index_all(migrated_engine, world)
    with Session(migrated_engine) as s, s.begin():
        newer = _store(
            s, world.storage, world.company, 2, b"Huurovereenkomst Anouk, versie 2. Huisdieren verboden.", "v2"
        )
    assert index_brixx_document(migrated_engine, world.storage, Reader(), HashingEmbedder(), world.company, newer)
    with Session(migrated_engine) as s:
        texts = " ".join(s.scalars(select(DocumentChunk.text).join(DocumentRow).where(
            DocumentRow.title == "Huurovereenkomst Anouk")))  # fmt: skip
    assert "versie 2" in texts
    assert "schriftelijke toestemming" not in texts


def test_documents_of_an_erased_person_are_not_indexed(migrated_engine: Engine, world: World) -> None:
    with Session(migrated_engine) as s, s.begin():
        s.add(BrixxErasedRef(company_id=world.company, relatie_id=1))
    _index_all(migrated_engine, world)
    with Session(migrated_engine) as s:
        status = s.scalars(select(DocumentRow.status).where(DocumentRow.title == "Paspoort")).one()
    assert status is DocumentStatus.skipped


def test_the_download_workflow_and_the_sync_index_stored_documents(
    migrated_engine: Engine, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingestion.process import IngestDeps
    from app.workflows import brixx_documents, deps

    deps.set_deps(IngestDeps(engine=migrated_engine, storage=world.storage, enqueuer=None,  # type: ignore[arg-type]
                             gmail_mailbox=lambda a: None, whatsapp_media=lambda p: None, gmail_topic="t"))  # type: ignore[arg-type]  # fmt: skip
    deps.set_extractor(Reader())
    deps.set_embedder(HashingEmbedder())
    deps.set_engine(migrated_engine)
    try:
        assert brixx_documents.index_document_step(str(world.company), 2)
        assert brixx_documents.index_backlog_step(str(world.company)) == 3
    finally:
        deps.set_deps(None)
        deps.set_extractor(None)
        deps.set_embedder(None)
        deps.set_engine(None)


def test_erasure_removes_the_persons_brixx_documents(migrated_engine: Engine, world: World) -> None:
    from app.pipeline.gdpr import erase_person

    _index_all(migrated_engine, world)
    with Session(migrated_engine) as s, s.begin():
        erase_person(s, world.company, world.anouk)
    with Session(migrated_engine) as s:
        titles = set(s.scalars(select(DocumentRow.title).where(DocumentRow.company_id == world.company)))
        chunks = " ".join(s.scalars(select(DocumentChunk.text).where(DocumentChunk.company_id == world.company)))
    assert "Huurovereenkomst Anouk" not in titles
    assert "schriftelijke toestemming" not in chunks
    assert "Huurovereenkomst Bram" in titles


def test_a_mirror_without_its_label_tables_still_indexes(migrated_engine: Engine, world: World) -> None:
    """BRIXX may not list every lookup table: a missing one reads as no labels, never as a failed index."""
    with Session(migrated_engine) as s, s.begin():
        s.execute(sa.text("ALTER TABLE brixx.typ_documentcategorie RENAME TO typ_documentcategorie_away"))
    try:
        assert _index_all(migrated_engine, world) == 4
    finally:
        with Session(migrated_engine) as s, s.begin():
            s.execute(sa.text("ALTER TABLE brixx.typ_documentcategorie_away RENAME TO typ_documentcategorie"))

"""Astra's source chips open what they cite: links the server builds from its own rows, scoped to the company."""

from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts.sourced_answer import Source
from app.db.models import AttachmentRow, Company, DocumentRow
from app.superagent.source_links import with_links
from tests.integration.reload_support import case, connect, mail, person

pytestmark = pytest.mark.integration


def _document(engine: Engine, company_id: object, message_id: object, drive_id: str | None) -> str:
    with Session(engine) as s, s.begin():
        att = AttachmentRow(company_id=company_id, message_id=message_id, s3_key="k", mime_type="application/pdf",
                            filename="lease.pdf", size_bytes=1, sha256=uuid4().hex * 2)  # fmt: skip
        s.add(att)
        s.flush()
        doc = DocumentRow(company_id=company_id, attachment_id=att.id, doc_type="lease", title="Lease",
                          file_name="lease.pdf", confidence=0.9, drive_file_id=drive_id)  # fmt: skip
        s.add(doc)
        s.flush()
        return str(doc.id)


def test_message_and_document_sources_link_to_their_thread_and_file(
    migrated_engine: Engine, committed_company: Company
) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    case_id = case(migrated_engine, cid, person(migrated_engine, cid))
    linked = mail(migrated_engine, cid, case_id=case_id, thread="s1")
    loose = mail(migrated_engine, cid, thread="s2")
    filed = _document(migrated_engine, cid, linked.message_id, "drv-1")
    unfiled = _document(migrated_engine, cid, loose.message_id, None)
    sources = (
        Source(kind="message", ref=str(linked.message_id), label="Sanne"),
        Source(kind="message", ref=str(loose.message_id), label="Unlinked"),
        Source(kind="document", ref=filed, label="Lease"),
        Source(kind="document", ref=unfiled, label="Not in Drive"),
        Source(kind="message", ref=str(uuid4()), label="Not ours"),
        Source(kind="web", ref="https://wetten.overheid.nl/x", label="wetten.overheid.nl"),
    )
    got = [s.href for s in with_links(migrated_engine, cid, sources)]
    assert got == [
        f"/inbox?thread={case_id}",
        None,
        "https://drive.google.com/file/d/drv-1/view",
        None,
        None,
        "https://wetten.overheid.nl/x",
    ]


def test_another_companys_rows_never_get_a_link(migrated_engine: Engine, committed_company: Company) -> None:
    cid = committed_company.id
    connect(migrated_engine, cid)
    case_id = case(migrated_engine, cid, person(migrated_engine, cid))
    linked = mail(migrated_engine, cid, case_id=case_id, thread="s3")
    with Session(migrated_engine) as s, s.begin():
        other = Company(name="Other")
        s.add(other)
        s.flush()
        other_id = other.id
    got = with_links(migrated_engine, other_id, (Source(kind="message", ref=str(linked.message_id), label="x"),))
    assert got[0].href is None

"""Document library API against real Postgres: search, detail, owner links; scoped, CSRF-guarded, route order."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.api.v1.auth import COOKIE, CSRF_HEADER, CSRF_VALUE, Principal, issue_session
from app.contracts import Channel, Direction
from app.core.settings import Settings
from app.db.enums import DocumentStatus, PersonKind
from app.db.models import (
    AttachmentRow,
    Company,
    DocumentChunk,
    DocumentLink,
    DocumentRow,
    MessageRow,
    OwnerAccount,
    Person,
    RawEvent,
)
from app.main import create_app
from tests.integration.access_support import add_person_to_team, build_app, signed_in
from tests.integration.conftest import purge_company

pytestmark = pytest.mark.integration
CSRF = {CSRF_HEADER: CSRF_VALUE}


@dataclass
class Fixture:
    client: TestClient
    mine: UUID  # a filed lease with chunks
    review: UUID
    theirs: UUID  # another company's document
    my_person: UUID
    their_person: UUID
    engine: Engine
    company_id: UUID
    pg_url: str


def _doc(s: Session, cid: UUID, title: str, status: DocumentStatus, text: str) -> UUID:
    raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(uuid4()), payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
                     thread_ref="t", sender_identity="x@y.test", direction=Direction.inbound,
                     sent_at=datetime(2026, 1, 1, tzinfo=UTC), text="hi")  # fmt: skip
    s.add(msg)
    s.flush()
    att = AttachmentRow(company_id=cid, message_id=msg.id, s3_key="k", mime_type="application/pdf", filename=title,
                        size_bytes=1, sha256="0" * 64)  # fmt: skip
    s.add(att)
    s.flush()
    doc = DocumentRow(company_id=cid, attachment_id=att.id, doc_type="lease", title=title, file_name=title,
                      confidence=0.9, status=status, document_date=date(2026, 1, 1), drive_file_id="drv")  # fmt: skip
    s.add(doc)
    s.flush()
    s.add(DocumentChunk(company_id=cid, document_id=doc.id, ord=0, text=text))
    return doc.id


@pytest.fixture
def fx(migrated_engine: Engine, pg_url: str, committed_company: Company) -> Iterator[Fixture]:
    with Session(migrated_engine, expire_on_commit=False) as s:
        other = Company(name="Other")
        s.add(other)
        s.flush()
        owner = OwnerAccount(company_id=committed_company.id, display_name="H", whatsapp_e164="+31699999994",
                             email="h@a.test")  # fmt: skip
        mine_p = Person(company_id=committed_company.id, kind=PersonKind.tenant, display_name="Anna",
                        valid_from=date(2025, 1, 1))  # fmt: skip
        their_p = Person(company_id=other.id, kind=PersonKind.tenant, display_name="Eve", valid_from=date(2025, 1, 1))
        s.add_all([owner, mine_p, their_p])
        s.flush()
        mine = _doc(
            s, committed_company.id, "Huurovereenkomst", DocumentStatus.filed, "De waarborgsom is twee maanden."
        )
        review = _doc(s, committed_company.id, "Onbekend", DocumentStatus.review, "Notitie over de waarborgsom.")
        theirs = _doc(s, other.id, "Eve lease", DocumentStatus.filed, "Geheime waarborgsom van Eve.")
        s.commit()
    settings = Settings(database_url=pg_url, env="test", dashboard_session_secret=SecretStr("x" * 32),  # type: ignore[arg-type]
                        _env_file=None)  # fmt: skip
    principal = Principal(company_id=committed_company.id, owner_id=owner.id, email="h@a.test")
    with TestClient(create_app(settings, engine=migrated_engine, workflow_client=MagicMock())) as c:
        c.cookies.set(COOKIE, issue_session(settings, principal, datetime.now(UTC)))
        yield Fixture(c, mine, review, theirs, mine_p.id, their_p.id, migrated_engine, committed_company.id, pg_url)
    purge_company(migrated_engine, other.id)


def test_search_finds_only_my_documents(fx: Fixture) -> None:
    body = fx.client.get("/api/v1/documents", params={"q": "waarborgsom"}).json()
    assert {d["id"] for d in body} == {str(fx.mine), str(fx.review)}
    assert "«waarborgsom»" in (body[0]["snippet"] or "")
    assert body[0]["drive_url"] == "https://drive.google.com/file/d/drv/view"


def test_filters_without_a_query_list_newest_first(fx: Fixture) -> None:
    body = fx.client.get("/api/v1/documents", params={"status": "review"}).json()
    assert [d["id"] for d in body] == [str(fx.review)]
    assert fx.client.get("/api/v1/documents", params={"type": "invoice"}).json() == []


def test_question_style_search_with_match_any(fx: Fixture) -> None:
    body = fx.client.get("/api/v1/documents", params={"q": "wat is de waarborgsom?", "match": "any"}).json()
    assert str(fx.mine) in {d["id"] for d in body}


def test_detail_and_foreign_ids_are_404(fx: Fixture) -> None:
    detail = fx.client.get(f"/api/v1/documents/{fx.mine}").json()
    assert (detail["title"], detail["chunk_count"], detail["links"]) == ("Huurovereenkomst", 1, [])
    assert fx.client.get(f"/api/v1/documents/{fx.theirs}").status_code == 404
    assert fx.client.get(f"/api/v1/documents/{uuid4()}").status_code == 404


def test_review_route_is_not_swallowed_by_the_id_route(fx: Fixture) -> None:
    resp = fx.client.get("/api/v1/documents/review")
    assert resp.status_code == 200
    assert [d["suggested_type"] for d in resp.json()] == ["lease"]


def test_owner_can_link_and_unlink_and_it_sticks(fx: Fixture) -> None:
    url = f"/api/v1/documents/{fx.mine}/links"
    assert fx.client.post(url, json={"kind": "person", "ref_id": str(fx.my_person)}).status_code == 403  # no CSRF
    assert fx.client.post(url, json={"kind": "person", "ref_id": str(fx.my_person)}, headers=CSRF).status_code == 204
    links = fx.client.get(f"/api/v1/documents/{fx.mine}").json()["links"]
    assert [(x["kind"], x["label"], x["method"]) for x in links] == [("person", "Anna", "owner")]
    assert fx.client.get("/api/v1/documents", params={"person_id": str(fx.my_person)}).json()[0]["id"] == str(fx.mine)
    gone = fx.client.delete(f"{url}/person/{fx.my_person}", headers=CSRF)
    assert gone.status_code == 204
    assert fx.client.get(f"/api/v1/documents/{fx.mine}").json()["links"] == []
    assert fx.client.get("/api/v1/documents", params={"person_id": str(fx.my_person)}).json() == []
    with Session(fx.engine) as s:
        assert s.scalar(select(DocumentLink.method).where(DocumentLink.document_id == fx.mine)) == "removed"


def test_cannot_link_to_another_companys_person_or_document(fx: Fixture) -> None:
    mine = f"/api/v1/documents/{fx.mine}/links"
    assert (
        fx.client.post(mine, json={"kind": "person", "ref_id": str(fx.their_person)}, headers=CSRF).status_code == 404
    )
    theirs = f"/api/v1/documents/{fx.theirs}/links"
    assert fx.client.post(theirs, json={"kind": "person", "ref_id": str(fx.my_person)}, headers=CSRF).status_code == 404


def test_unauthenticated_requests_are_refused(fx: Fixture) -> None:
    fx.client.cookies.clear()
    assert fx.client.get("/api/v1/documents").status_code == 401
    assert fx.client.get(f"/api/v1/documents/{fx.mine}").status_code == 401


def test_bad_inputs_are_422(fx: Fixture) -> None:
    assert fx.client.get("/api/v1/documents", params={"q": "x" * 201}).status_code == 422
    assert fx.client.get("/api/v1/documents", params={"limit": 0}).status_code == 422
    assert fx.client.get("/api/v1/documents", params={"status": "nope"}).status_code == 422
    assert fx.client.get("/api/v1/documents/not-a-uuid").status_code == 422


def test_titles_summaries_and_snippets_never_carry_links_or_bank_accounts(fx: Fixture) -> None:
    risky = "Pay NL91ABNA0417164300 via https://evil.example/pay"
    with Session(fx.engine) as s, s.begin():
        doc = s.get(DocumentRow, fx.mine)
        assert doc is not None
        doc.title, doc.summary = f"Huur {risky}", risky
        s.add(DocumentChunk(company_id=doc.company_id, document_id=doc.id, ord=1, text=f"De waarborgsom: {risky}"))
    for body in (
        fx.client.get("/api/v1/documents", params={"q": "waarborgsom"}).json(),
        [fx.client.get(f"/api/v1/documents/{fx.mine}").json()],
    ):
        shown = str(body)
        assert "evil.example" not in shown
        assert "NL91" not in shown


def test_hybrid_search_finds_across_languages_where_word_search_does_not(fx: Fixture) -> None:
    from app.llm.embeddings import HashingEmbedder
    from app.pipeline.document_embed import embed_chunks, embed_documents_summary

    with Session(fx.engine) as s:
        cid = s.scalars(select(DocumentRow.company_id).where(DocumentRow.id == fx.mine)).one()
        s.execute(DocumentRow.__table__.update().where(DocumentRow.company_id == cid).values(index_version="r2"))
        s.commit()
    embed_chunks(fx.engine, HashingEmbedder(), cid)
    embed_documents_summary(fx.engine, HashingEmbedder(), cid)
    hybrid = fx.client.get("/api/v1/documents", params={"q": "deposit", "mode": "hybrid"}).json()
    words = fx.client.get("/api/v1/documents", params={"q": "deposit", "mode": "words"}).json()
    assert str(fx.mine) in {d["id"] for d in hybrid}
    assert words == []  # the English word is nowhere in the Dutch text
    assert str(fx.theirs) not in {d["id"] for d in hybrid}  # another company's document is never ranked


def test_hybrid_is_the_default_mode_and_keeps_highlights_for_matching_words(fx: Fixture) -> None:
    body = fx.client.get("/api/v1/documents", params={"q": "waarborgsom"}).json()
    assert "«waarborgsom»" in (body[0]["snippet"] or "")


def test_owner_can_toggle_reference_library(fx: Fixture) -> None:
    url = f"/api/v1/documents/{fx.mine}/reference"
    assert fx.client.post(url, json={"is_reference": True}).status_code == 403
    for doc_id in (fx.theirs, uuid4()):
        resp = fx.client.post(f"/api/v1/documents/{doc_id}/reference", json={"is_reference": True}, headers=CSRF)
        assert resp.status_code == 404

    on = fx.client.post(url, json={"is_reference": True}, headers=CSRF)
    assert on.status_code == 200
    assert on.json() == {"id": str(fx.mine), "is_reference": True}
    assert fx.client.get(f"/api/v1/documents/{fx.mine}").json()["is_reference"] is True
    ref_docs = fx.client.get("/api/v1/documents", params={"reference_only": True}).json()
    assert [d["id"] for d in ref_docs] == [str(fx.mine)]

    off = fx.client.post(url, json={"is_reference": False}, headers=CSRF)
    assert off.status_code == 200
    assert off.json() == {"id": str(fx.mine), "is_reference": False}
    assert fx.client.get("/api/v1/documents", params={"reference_only": True}).json() == []


def test_a_tenants_own_papers_never_become_reference_documents(fx: Fixture) -> None:
    """Every dossier reads the reference library: a lease linked to a tenant, or anyone's ID, would reach the drafts
    to every other tenant."""
    url = f"/api/v1/documents/{fx.mine}/reference"
    with Session(fx.engine) as s, s.begin():
        link = DocumentLink(company_id=fx.company_id, document_id=fx.mine, kind="person", ref_id=fx.my_person,
                            method="owner", score=1.0)  # fmt: skip
        s.add(link)
    linked = fx.client.post(url, json={"is_reference": True}, headers=CSRF)
    assert linked.status_code == 409
    with Session(fx.engine) as s, s.begin():
        s.execute(update(DocumentLink).where(DocumentLink.document_id == fx.mine).values(kind="unit"))
        s.execute(update(DocumentRow).where(DocumentRow.id == fx.review).values(doc_type="id_document"))
    assert fx.client.post(url, json={"is_reference": True}, headers=CSRF).status_code == 409
    review_url = f"/api/v1/documents/{fx.review}/reference"
    assert fx.client.post(review_url, json={"is_reference": True}, headers=CSRF).status_code == 409
    assert fx.client.get("/api/v1/documents", params={"reference_only": True}).json() == []
    assert fx.client.post(url, json={"is_reference": False}, headers=CSRF).status_code == 200  # unmarking always works


def test_only_an_admin_may_change_the_reference_library(fx: Fixture) -> None:
    """A promoted document reaches every draft, so a maintenance member may read documents but not promote one."""
    member = add_person_to_team(
        fx.engine, fx.company_id, f"m-{uuid4().hex[:6]}@t.test", role="member", sections=["maintenance"]
    )
    app, settings = build_app(fx.engine, fx.pg_url)
    with signed_in(app, settings, member) as client:
        resp = client.post(f"/api/v1/documents/{fx.mine}/reference", json={"is_reference": True}, headers=CSRF)
    assert resp.status_code == 403

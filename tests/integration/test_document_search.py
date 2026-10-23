"""M10 document search against Postgres: ranking, snippets, filters, metadata fallback, scoping, hostile queries."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.enums import DocLinkKind, DocumentStatus, PersonKind
from app.db.models import (
    AttachmentRow,
    Company,
    DocumentChunk,
    DocumentLink,
    DocumentRow,
    MessageRow,
    Person,
    RawEvent,
    Unit,
)
from app.pipeline.document_search import DocFilter, any_of, get_document, list_documents, search_documents

pytestmark = pytest.mark.integration


@dataclass
class Corpus:
    company_id: UUID
    lease_doc: UUID
    invoice_doc: UUID
    quote_doc: UUID
    anna: UUID
    unit: UUID


def _doc(
    s: Session, cid: UUID, *, title: str, doc_type: str, chunks: list[str],
    status: DocumentStatus = DocumentStatus.filed, day: date | None = None, summary: str | None = None,
) -> UUID:  # fmt: skip
    raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
    s.add(raw)
    s.flush()
    msg = MessageRow(company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
                     thread_ref="t", sender_identity="x@example.test", direction=Direction.inbound,
                     sent_at=datetime(2026, 10, 6, tzinfo=UTC), text="t", meta={})  # fmt: skip
    s.add(msg)
    s.flush()
    att = AttachmentRow(company_id=cid, message_id=msg.id, s3_key="k", mime_type="application/pdf",
                        filename=f"{title}.pdf", size_bytes=9, sha256="0" * 64)  # fmt: skip
    s.add(att)
    s.flush()
    doc = DocumentRow(company_id=cid, attachment_id=att.id, doc_type=doc_type, title=title, file_name=f"{title}.pdf",
                      confidence=0.9, status=status, document_date=day, summary=summary,
                      drive_file_id="drv1")  # fmt: skip
    s.add(doc)
    s.flush()
    for i, text in enumerate(chunks):
        s.add(DocumentChunk(company_id=cid, document_id=doc.id, ord=i, text=text))
    return doc.id


@pytest.fixture
def corpus(migrated_engine: Engine, committed_company: Company) -> Corpus:
    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        anna = Person(company_id=cid, kind=PersonKind.tenant, display_name="Anna de Vries", valid_from=date(2025, 1, 1))
        unit = Unit(company_id=cid, label="Kerkstraat 12-2", valid_from=date(2025, 1, 1))
        s.add_all([anna, unit])
        s.flush()
        lease = _doc(s, cid, title="Huurovereenkomst Kerkstraat", doc_type="lease", day=date(2025, 1, 1),
                     chunks=["De huurder betaalt een waarborgsom van twee maanden kale huur.",
                             "De opzegtermijn is drie maanden. Onderhoud is voor de verhuurder."])  # fmt: skip
        invoice = _doc(s, cid, title="Factuur loodgieter", doc_type="invoice", day=date(2026, 9, 3),
                       chunks=["Factuur voor reparatie van de waterleiding. Totaal EUR 245,00."])  # fmt: skip
        quote = _doc(s, cid, title="Offerte dakreparatie", doc_type="quote", status=DocumentStatus.review,
                     chunks=["Offerte dak: vervangen van dakpannen, waterleiding blijft ongemoeid."],
                     summary="Roof repair quote")  # fmt: skip
        for doc_id, kind, ref in ((lease, DocLinkKind.person, anna.id), (lease, DocLinkKind.unit, unit.id),
                                  (invoice, DocLinkKind.unit, unit.id)):  # fmt: skip
            s.add(DocumentLink(company_id=cid, document_id=doc_id, kind=kind, ref_id=ref, method="fuzzy", score=0.9))
        return Corpus(cid, lease, invoice, quote, anna.id, unit.id)


def _search(engine: Engine, c: Corpus, query: str, flt: DocFilter = DocFilter()) -> list[UUID]:  # noqa: B008
    with Session(engine) as s:
        return [h.document_id for h in search_documents(s, c.company_id, query, flt)]


def test_finds_a_document_by_what_it_says_with_a_highlighted_snippet(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s:
        hits = search_documents(s, corpus.company_id, "waarborgsom")
    assert [h.document_id for h in hits] == [corpus.lease_doc]
    assert hits[0].snippet is not None
    assert "«waarborgsom»" in hits[0].snippet
    assert hits[0].drive_url == "https://drive.google.com/file/d/drv1/view"


def test_dutch_stemming_finds_plural_and_inflected_forms(migrated_engine: Engine, corpus: Corpus) -> None:
    assert _search(migrated_engine, corpus, "huurders") == [corpus.lease_doc]
    assert _search(migrated_engine, corpus, "opzegtermijnen") == [corpus.lease_doc]


def test_ranks_the_better_match_first(migrated_engine: Engine, corpus: Corpus) -> None:
    assert _search(migrated_engine, corpus, "waterleiding reparatie") == [corpus.invoice_doc]  # every word
    with Session(migrated_engine) as s:
        any_word = [
            h.document_id for h in search_documents(s, corpus.company_id, "waterleiding reparatie", match="any")
        ]
    assert any_word == [corpus.invoice_doc, corpus.quote_doc]  # best overlap first


def test_metadata_matches_come_after_content_matches(migrated_engine: Engine, corpus: Corpus) -> None:
    got = _search(migrated_engine, corpus, "roof")  # only in the summary of the quote
    assert got == [corpus.quote_doc]


def test_filters_by_type_person_unit_status_and_date(migrated_engine: Engine, corpus: Corpus) -> None:
    def ids(flt: DocFilter) -> set[UUID]:
        with Session(migrated_engine) as s:
            return {h.document_id for h in list_documents(s, corpus.company_id, flt)}

    assert ids(DocFilter(doc_type="invoice")) == {corpus.invoice_doc}
    assert ids(DocFilter(person_id=corpus.anna)) == {corpus.lease_doc}
    assert ids(DocFilter(unit_id=corpus.unit)) == {corpus.lease_doc, corpus.invoice_doc}
    assert ids(DocFilter(status=DocumentStatus.review)) == {corpus.quote_doc}
    assert ids(DocFilter(date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))) == {
        corpus.invoice_doc,
        corpus.quote_doc,
    }
    assert _search(migrated_engine, corpus, "waterleiding", DocFilter(unit_id=corpus.unit)) == [corpus.invoice_doc]


def test_removed_links_do_not_count(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s, s.begin():
        link = s.query(DocumentLink).filter_by(document_id=corpus.invoice_doc, ref_id=corpus.unit).one()
        link.method = "removed"
    with Session(migrated_engine) as s:
        assert {h.document_id for h in list_documents(s, corpus.company_id, DocFilter(unit_id=corpus.unit))} == {
            corpus.lease_doc
        }


def test_failed_and_skipped_documents_are_not_searchable(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s, s.begin():
        s.query(DocumentRow).filter_by(id=corpus.invoice_doc).update({"status": DocumentStatus.failed})
    assert _search(migrated_engine, corpus, "Factuur") == []


def test_another_company_sees_nothing(migrated_engine: Engine, corpus: Corpus) -> None:
    assert (
        _search(migrated_engine, Corpus(new_id(), *([corpus.lease_doc] * 3), corpus.anna, corpus.unit), "huurder") == []
    )
    with Session(migrated_engine) as s, pytest.raises(NotFoundError):
        get_document(s, new_id(), corpus.lease_doc)


@pytest.mark.parametrize("query", ["' OR 1=1 --", "a & | ! (", '"', "%", "huur:*", "\\", "x" * 5000, "   "])
def test_hostile_or_odd_queries_never_error(migrated_engine: Engine, corpus: Corpus, query: str) -> None:
    _search(migrated_engine, corpus, query)


def test_percent_in_a_query_is_literal_for_the_metadata_fallback(migrated_engine: Engine, corpus: Corpus) -> None:
    assert _search(migrated_engine, corpus, "%") == []


def test_detail_has_facts_links_and_unresolved(migrated_engine: Engine, corpus: Corpus) -> None:
    facts = {"parties": [], "unit_hint": None, "start_date": None, "end_date": None, "key_facts": [],
             "unresolved": ["person: Pieter Jansen"]}  # fmt: skip
    with Session(migrated_engine) as s, s.begin():
        s.query(DocumentRow).filter_by(id=corpus.lease_doc).update({"facts": facts})
    with Session(migrated_engine) as s:
        detail = get_document(s, corpus.company_id, corpus.lease_doc)
    assert detail.unresolved == ["person: Pieter Jansen"]
    assert detail.facts is not None
    assert "unresolved" not in detail.facts
    assert {(r.kind, r.label) for r in detail.links} == {
        (DocLinkKind.person, "Anna de Vries"), (DocLinkKind.unit, "Kerkstraat 12-2")
    }  # fmt: skip
    assert detail.chunk_count == 2


def test_needs_link_filter(migrated_engine: Engine, corpus: Corpus) -> None:
    facts = {"parties": [], "unit_hint": None, "start_date": None, "end_date": None, "key_facts": [],
             "unresolved": ["unit: Kerkstraat 12"]}  # fmt: skip
    with Session(migrated_engine) as s, s.begin():
        s.query(DocumentRow).filter_by(id=corpus.quote_doc).update({"facts": facts})
    with Session(migrated_engine) as s:
        got = {h.document_id for h in list_documents(s, corpus.company_id, DocFilter(needs_link=True))}
    assert got == {corpus.quote_doc}


def test_any_of_builds_an_or_query_from_the_words() -> None:
    assert any_of("What does the lease say about the deposit?") == "lease or deposit"
    assert any_of("a b") == "a b"
    assert any_of("de van") == "de van"  # nothing left after the stop words: keep the query as typed

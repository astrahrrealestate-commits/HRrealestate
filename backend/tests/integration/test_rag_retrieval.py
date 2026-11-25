"""Hybrid retrieval against Postgres + pgvector: words, vectors, fusion, filters, scoping, graceful degradation."""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.enums import DocLinkKind
from app.db.models import Company, DocumentLink, DocumentRow
from app.llm.embeddings import HashingEmbedder
from app.pipeline.document_embed import embed_chunks, embed_documents_summary
from app.pipeline.document_search import DocFilter
from app.pipeline.rag_retrieval import (
    document_ranking,
    hybrid_candidates,
    rrf,
    vector_ranking,
    words_query,
    words_ranking,
)
from tests.integration.test_document_search import _doc

pytestmark = pytest.mark.integration
EMBED = HashingEmbedder()


@dataclass
class Corpus:
    company_id: UUID
    lease: UUID
    invoice: UUID
    other_lease: UUID
    case_id: UUID


@pytest.fixture
def corpus(migrated_engine: Engine, committed_company: Company) -> Corpus:
    from app.contracts import CaseState, Category, Urgency
    from app.db.models import Case

    cid = committed_company.id
    with Session(migrated_engine) as s, s.begin():
        lease_chunks = ["De waarborgsom bedraagt twee maanden kale huur.", "De opzegtermijn is drie maanden."]
        lease = _doc(s, cid, title="Huurovereenkomst Kerkstraat", doc_type="lease", day=date(2026, 1, 1),
                     chunks=lease_chunks)  # fmt: skip
        other = _doc(s, cid, title="Huur Zeestraat", doc_type="lease", day=date(2025, 1, 1),
                     chunks=["De waarborgsom bedraagt drie maanden kale huur."])  # fmt: skip
        invoice = _doc(s, cid, title="Factuur loodgieter", doc_type="invoice", day=date(2026, 9, 3),
                       chunks=["Reparatie van de waterleiding. Totaal EUR 245,00."])  # fmt: skip
        case = Case(company_id=cid, state=CaseState.open, category=Category.administration, urgency=Urgency.normal)
        s.add(case)
        s.flush()
        s.add(
            DocumentLink(
                company_id=cid, document_id=lease, kind=DocLinkKind.case, ref_id=case.id, method="message", score=1.0
            )
        )
        s.execute(DocumentRow.__table__.update().where(DocumentRow.company_id == cid).values(index_version="r2"))
        case_id = case.id
    embed_chunks(migrated_engine, EMBED, cid)
    embed_documents_summary(migrated_engine, EMBED, cid)
    return Corpus(cid, lease, invoice, other, case_id)


def test_rrf_rewards_agreement_and_lets_one_strong_list_surface_an_item() -> None:
    a, b, c = (UUID(int=i) for i in (1, 2, 3))
    fused = rrf([(1.0, [a, b]), (1.0, [b, c])])
    assert fused[b] > fused[a]
    assert fused[b] > fused[c]
    assert c in fused  # present in one list only
    assert rrf([(1.0, [])]) == {}
    assert rrf([(2.0, [a])])[a] == pytest.approx(2.0 / 61)


def test_words_query_adds_the_other_language_and_drops_filler() -> None:
    q = words_query("What does the lease say about the deposit?")
    assert "waarborgsom" in q
    assert "what" not in q.split(" or ")


def test_words_only_misses_what_the_vector_side_finds_across_languages(migrated_engine: Engine, corpus: Corpus) -> None:
    question = "What is the deposit?"
    with Session(migrated_engine) as s:
        raw = words_ranking(s, corpus.company_id, "deposit", DocFilter())  # no glossary: English word, Dutch text
        vec = vector_ranking(s, corpus.company_id, EMBED.embed_query(question), DocFilter())
        docs = document_ranking(s, corpus.company_id, EMBED.embed_query(question), DocFilter())
    assert raw == []
    assert vec  # the vector list ranks chunks of every document, the deposit chunks first
    assert set(docs) >= {corpus.lease}


def test_hybrid_puts_the_deposit_clause_first_for_an_english_question(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s:
        got = hybrid_candidates(s, corpus.company_id, "What is the deposit?", DocFilter(), EMBED)
    assert "waarborgsom" in got[0].text
    assert {got[0].document_id} <= {corpus.lease, corpus.other_lease}
    assert got[0].vector_rank is not None
    assert got[0].words_rank is not None  # the glossary reached it on the words side too
    assert [c.score for c in got] == sorted((c.score for c in got), reverse=True)


def test_without_an_embedder_the_words_list_still_answers(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s:
        got = hybrid_candidates(s, corpus.company_id, "waarborgsom", DocFilter(), None)
    assert got
    assert all(c.vector_rank is None for c in got)


def test_chunks_without_vectors_are_still_found_by_words(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s, s.begin():
        s.execute(DocumentRow.__table__.update().values(doc_embedding=None))
        from app.db.models import DocumentChunk

        s.execute(DocumentChunk.__table__.update().values(embedding=None))
    with Session(migrated_engine) as s:
        got = hybrid_candidates(s, corpus.company_id, "opzegtermijn", DocFilter(), EMBED)
    assert got
    assert "opzegtermijn" in got[0].text


def test_case_scope_filter_limits_every_list(migrated_engine: Engine, corpus: Corpus) -> None:
    scope = DocFilter(any_link=((DocLinkKind.case, corpus.case_id),))
    with Session(migrated_engine) as s:
        got = hybrid_candidates(s, corpus.company_id, "waarborgsom huur", scope, EMBED)
    assert got
    assert {c.document_id for c in got} == {corpus.lease}


def test_suspicious_documents_are_dropped_when_asked(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s, s.begin():
        s.get(DocumentRow, corpus.other_lease).suspicious = True  # type: ignore[union-attr]
    with Session(migrated_engine) as s:
        plain = {c.document_id for c in hybrid_candidates(s, corpus.company_id, "waarborgsom", DocFilter(), EMBED)}
        safe = {
            c.document_id
            for c in hybrid_candidates(s, corpus.company_id, "waarborgsom", DocFilter(readable_only=True), EMBED)
        }
    assert corpus.other_lease in plain
    assert corpus.other_lease not in safe


def test_another_company_gets_nothing(migrated_engine: Engine, corpus: Corpus) -> None:
    from app.core.ids import new_id

    with Session(migrated_engine) as s:
        assert hybrid_candidates(s, new_id(), "waarborgsom", DocFilter(), EMBED) == []


@pytest.mark.parametrize("question", ["' OR 1=1 --", "a & | ! (", "%", "\\", "x" * 3000, "   ", "deposit:*"])
def test_hostile_questions_never_error(migrated_engine: Engine, corpus: Corpus, question: str) -> None:
    with Session(migrated_engine) as s:
        hybrid_candidates(s, corpus.company_id, question, DocFilter(), EMBED)


def test_hyde_text_and_variants_reach_their_sides(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s:
        got = hybrid_candidates(
            s, corpus.company_id, "hoeveel is het?", DocFilter(), EMBED,
            variants=["opzegtermijn"], dense_texts=["De opzegtermijn is drie maanden."],
        )  # fmt: skip
    assert "opzegtermijn" in got[0].text


class Broken(HashingEmbedder):
    def embed_documents(self, texts):  # type: ignore[no-untyped-def]
        raise ValueError("401 invalid api key")  # not a transient error: a bad or expired key


def test_any_embedder_failure_degrades_to_words_and_is_not_raised(migrated_engine: Engine, corpus: Corpus) -> None:
    with Session(migrated_engine) as s:
        got = hybrid_candidates(s, corpus.company_id, "waarborgsom", DocFilter(), Broken())
    assert got
    assert all(c.vector_rank is None for c in got)


def test_another_companys_document_vectors_never_rank(migrated_engine: Engine, corpus: Corpus) -> None:
    from app.core.ids import new_id

    q = EMBED.embed_query("waarborgsom")
    with Session(migrated_engine) as s:
        assert document_ranking(s, new_id(), q, DocFilter()) == []
        assert vector_ranking(s, new_id(), q, DocFilter()) == []

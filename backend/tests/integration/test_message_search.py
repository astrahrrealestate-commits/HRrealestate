"""Message search on Postgres + pgvector with the offline models: any-word matching, both languages, filters, the
reranker's floor and fallback, and what the indexer embeds."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.contracts import Channel, Direction
from app.core.ids import new_id
from app.core.settings import Settings
from app.db.enums import PersonKind
from app.db.models import Company, MessageChunk, MessageRow, Person, RawEvent
from app.llm.embeddings import HashingEmbedder
from app.pipeline.document_search import DocFilter
from app.pipeline.rag_retrieval import hybrid_candidates
from app.tools.message_rag import indexer, rerank
from app.tools.message_rag.indexer import index_message
from app.tools.message_rag.rerank import rerank_hits
from app.tools.message_rag.search import MessageChunkHit, search_messages

pytestmark = pytest.mark.integration
EMBED = HashingEmbedder()


class RecordingEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.documents: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return super().embed_query(text)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return super().embed_documents(texts)


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake", "embedding_model": "fake"})


def _person(engine: Engine, cid: UUID, name: str) -> UUID:
    with Session(engine) as s, s.begin():
        p = Person(company_id=cid, kind=PersonKind.tenant, display_name=name, valid_from=date(2025, 1, 1))
        s.add(p)
        s.flush()
        return p.id


def _mail(engine: Engine, cid: UUID, text: str, person_id: UUID | None = None, thread: str | None = None) -> UUID:
    with Session(engine) as s, s.begin():
        raw = RawEvent(company_id=cid, provider=Channel.gmail, provider_msg_id=str(new_id()), payload={})
        s.add(raw)
        s.flush()
        msg = MessageRow(
            company_id=cid, raw_event_id=raw.id, channel=Channel.gmail, provider_msg_id=raw.provider_msg_id,
            thread_ref=thread or raw.provider_msg_id, sender_identity="a@example.test", direction=Direction.inbound,
            sent_at=datetime(2026, 9, 1, 9, tzinfo=UTC), text=text, person_id=person_id, meta={},
        )  # fmt: skip
        s.add(msg)
        s.flush()
        return msg.id


def _indexed(engine: Engine, settings: Settings, cid: UUID, text: str, person_id: UUID | None = None) -> UUID:
    mid = _mail(engine, cid, text, person_id)
    assert index_message(engine, settings, mid) == "indexed"
    return mid


def _words_only(engine: Engine, cid: UUID, query: str, **kw: object) -> list[MessageChunkHit]:
    with Session(engine) as s:
        return search_messages(s, cid, query, None, **kw)  # type: ignore[arg-type]


def test_a_natural_question_finds_a_chunk_without_every_word(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    mid = _indexed(migrated_engine, settings, committed_company.id, "De loodgieter vraagt 480 euro voor de afvoer.")
    hits = _words_only(migrated_engine, committed_company.id, "Hoeveel vroeg de loodgieter eerst voor de badkamer?")
    assert [h.first_message_id for h in hits] == [mid]


def test_english_question_finds_dutch_mail(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    mid = _indexed(migrated_engine, settings, committed_company.id, "De waarborgsom is op 31 juli ontvangen.")
    _indexed(migrated_engine, settings, committed_company.id, "De schilder komt maandag.")
    hits = _words_only(migrated_engine, committed_company.id, "Was the deposit received?")
    assert hits[0].first_message_id == mid


def test_or_words_and_rerank_keep_every_filter(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    anna, bram = _person(migrated_engine, cid, "Anna"), _person(migrated_engine, cid, "Bram")
    mine = _indexed(migrated_engine, settings, cid, "Lekkage in de badkamer van Anna.", anna)
    _indexed(migrated_engine, settings, cid, "Lekkage in de badkamer van Bram.", bram)
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, "lekkage badkamer keuken", None, person_id=anna, date_to=date(2026, 9, 30))
        none = search_messages(s, cid, "lekkage badkamer", None, person_id=anna, date_from=date(2026, 10, 1))
        other_company = search_messages(s, new_id(), "lekkage badkamer", None)
        other_case = search_messages(s, cid, "lekkage badkamer keuken", EMBED, case_id=new_id())
    kept = rerank_hits(migrated_engine, settings, cid, "lekkage badkamer", hits)
    assert [h.first_message_id for h in kept] == [mine]
    assert none == []
    assert other_company == []
    assert other_case == []


def test_a_chunk_with_every_word_ranks_above_chunks_full_of_one(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    exact = _indexed(migrated_engine, settings, cid, "De cv op Keizersgracht 42 lekt.")
    for _ in range(3):
        _indexed(migrated_engine, settings, cid, "Keizersgracht Keizersgracht Keizersgracht Keizersgracht.")
    assert _words_only(migrated_engine, cid, "cv Keizersgracht 42")[0].first_message_id == exact


def test_header_words_are_not_search_terms(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    mould = _indexed(migrated_engine, settings, cid, "Er zit schimmel op de muur.")
    for _ in range(3):
        _indexed(migrated_engine, settings, cid, "Dank u wel.")
    hits = _words_only(migrated_engine, cid, "what did the tenant say on gmail about schimmel")
    assert [h.first_message_id for h in hits] == [mould]


def test_a_failing_vector_search_leaves_the_words_working(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    class Broken(HashingEmbedder):
        def embed_query(self, text: str) -> list[float]:
            return [0.0]  # the wrong size: the database refuses it

    cid = committed_company.id
    mid = _indexed(migrated_engine, settings, cid, "De lekkage is verholpen.")
    with Session(migrated_engine) as s:
        assert [h.first_message_id for h in search_messages(s, cid, "lekkage", Broken())] == [mid]


def test_rerank_drops_unhelpful_hits(migrated_engine: Engine, settings: Settings, committed_company: Company) -> None:
    cid = committed_company.id
    good = _indexed(migrated_engine, settings, cid, "De lekkage in de badkamer is verholpen door de loodgieter.")
    _indexed(migrated_engine, settings, cid, "Gefeliciteerd met uw verjaardag.")
    question = "Is de lekkage in de badkamer verholpen?"
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, question, EMBED)
    assert len(hits) == 2  # vectors alone return everything
    kept = rerank_hits(migrated_engine, settings, cid, question, hits)
    assert [h.first_message_id for h in kept] == [good]


def test_rerank_returns_nothing_when_nothing_helps(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    _indexed(migrated_engine, settings, cid, "De schilder komt maandag.")
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, "Wie wint het WK voetbal?", EMBED)
    assert hits
    assert rerank_hits(migrated_engine, settings, cid, "Wie wint het WK voetbal?", hits) == []


def test_rerank_sees_the_matching_part_of_a_long_chunk(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    filler = "Algemene opname zonder bijzonderheden. " * 45
    mid = _indexed(migrated_engine, settings, cid, f"{filler}De brandtrap wordt op 1 maart gekeurd.")
    question = "Wanneer wordt de brandtrap gekeurd?"
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, question, EMBED)
    assert [h.first_message_id for h in rerank_hits(migrated_engine, settings, cid, question, hits)] == [mid]


def test_rerank_failure_keeps_the_fused_order(
    migrated_engine: Engine, settings: Settings, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.errors import AgentFailedError

    def fail(*_a: object, **_k: object) -> None:
        raise AgentFailedError("down")

    cid = committed_company.id
    _indexed(migrated_engine, settings, cid, "De lekkage is verholpen.")
    _indexed(migrated_engine, settings, cid, "De schilder komt maandag.")
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, "lekkage", EMBED)
    monkeypatch.setattr(rerank, "run_agent", fail)
    assert rerank_hits(migrated_engine, settings, cid, "lekkage", hits) == hits


def test_rerank_can_be_switched_off(migrated_engine: Engine, settings: Settings, committed_company: Company) -> None:
    cid = committed_company.id
    _indexed(migrated_engine, settings, cid, "De lekkage is verholpen.")
    _indexed(migrated_engine, settings, cid, "De schilder komt maandag.")
    with Session(migrated_engine) as s:
        hits = search_messages(s, cid, "lekkage", EMBED)
    off = settings.model_copy(update={"rag_rerank": False})
    assert rerank_hits(migrated_engine, off, cid, "lekkage", hits) == hits


def test_chunks_are_embedded_as_documents(
    migrated_engine: Engine, settings: Settings, committed_company: Company, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingEmbedder()
    monkeypatch.setattr(indexer, "build_embedder", lambda _s: recorder)
    _indexed(migrated_engine, settings, committed_company.id, "De lekkage is verholpen.")
    assert recorder.queries == []
    assert len(recorder.documents) == 1
    assert "lekkage" in recorder.documents[0]


def test_a_document_question_is_a_query_and_its_hypothetical_answer_a_document(
    migrated_engine: Engine, committed_company: Company
) -> None:
    recorder = RecordingEmbedder()
    with Session(migrated_engine) as s:
        hybrid_candidates(
            s, committed_company.id, "Wat is de borg?", DocFilter(), recorder, dense_texts=["De borg is 2 maanden."]
        )
    assert recorder.queries == ["Wat is de borg?"]
    assert recorder.documents == ["De borg is 2 maanden."]


def test_reindexing_a_message_does_not_repeat_its_text(
    migrated_engine: Engine, settings: Settings, committed_company: Company
) -> None:
    cid = committed_company.id
    first = _mail(migrated_engine, cid, "De lekkage is verholpen.", thread="t1")
    second = _mail(migrated_engine, cid, "Dank u wel.", thread="t1")
    for mid in (first, second, second, first):
        index_message(migrated_engine, settings, mid)
    with Session(migrated_engine) as s:
        [chunk] = s.scalars(select(MessageChunk).where(MessageChunk.company_id == cid)).all()
    assert chunk.text.count("De lekkage is verholpen.") == 1
    assert chunk.text.count("Dank u wel.") == 1
    assert chunk.message_ids == [first, second]

"""What Astra's search tools hand to the model: reranked mail, planned and reranked document passages, the part of a
long text that answers, and nothing at all when nothing helps."""

from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import Company, DocumentRow
from app.llm.embeddings import HashingEmbedder
from app.pipeline.document_embed import embed_chunks, embed_documents_summary
from app.superagent.research import SNIPPET_CHARS, SuperAgentDeps, _documents, _messages, _messages_filtered
from tests.integration.test_document_search import _doc
from tests.integration.test_message_search import _indexed

pytestmark = pytest.mark.integration
EMBED = HashingEmbedder()


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake", "embedding_model": "fake"})


@pytest.fixture
def deps(migrated_engine: Engine, settings: Settings, committed_company: Company) -> SuperAgentDeps:
    return SuperAgentDeps(migrated_engine, settings, committed_company.id, EMBED)


def _document(engine: Engine, cid: UUID, title: str, chunks: list[str]) -> None:
    with Session(engine) as s, s.begin():
        _doc(s, cid, title=title, doc_type="lease", day=date(2026, 1, 1), chunks=chunks)
        s.execute(DocumentRow.__table__.update().where(DocumentRow.company_id == cid).values(index_version="r2"))
    embed_chunks(engine, EMBED, cid)
    embed_documents_summary(engine, EMBED, cid)


def test_astra_messages_are_reranked(deps: SuperAgentDeps) -> None:
    _indexed(deps.engine, deps.settings, deps.company_id, "De lekkage in de badkamer is verholpen.")
    _indexed(deps.engine, deps.settings, deps.company_id, "Gefeliciteerd met uw verjaardag.")
    text, count = _messages(deps, "Is de lekkage in de badkamer verholpen?")
    assert count == 1
    assert "verholpen" in text
    assert "verjaardag" not in text


def test_astra_filtered_messages_are_reranked_too(deps: SuperAgentDeps) -> None:
    _indexed(deps.engine, deps.settings, deps.company_id, "De lekkage in de badkamer is verholpen.")
    _indexed(deps.engine, deps.settings, deps.company_id, "Gefeliciteerd met uw verjaardag.")
    text, count = _messages_filtered(deps, "Is de lekkage in de badkamer verholpen?", channel="gmail")
    assert count == 1
    assert "verjaardag" not in text


def test_a_date_only_search_still_lists_the_mail(deps: SuperAgentDeps) -> None:
    _indexed(deps.engine, deps.settings, deps.company_id, "De schilder komt maandag.")
    text, count = _messages_filtered(deps, "", date_from="2026-09-01", date_to="2026-09-02")
    assert count == 1
    assert "schilder" in text


def test_the_snippet_of_a_long_mail_is_the_part_that_answers(deps: SuperAgentDeps) -> None:
    filler = "Algemene opname zonder bijzonderheden. " * 45
    _indexed(deps.engine, deps.settings, deps.company_id, f"{filler}De brandtrap wordt op 1 maart gekeurd.")
    text, _ = _messages(deps, "Wanneer wordt de brandtrap gekeurd?")
    assert "1 maart" in text
    assert len(text) < SNIPPET_CHARS + 200


def test_astra_documents_use_plan_and_rerank(deps: SuperAgentDeps) -> None:
    _document(deps.engine, deps.company_id, "Huurovereenkomst Kerkstraat", [
        "Artikel 9 Huisdieren. Het houden van huisdieren is niet toegestaan zonder toestemming.",
    ])  # fmt: skip
    _document(deps.engine, deps.company_id, "Factuur loodgieter", ["Reparatie van de waterleiding. Totaal EUR 245."])
    text, count = _documents(deps, "What does the lease say about pets?")
    assert count >= 1
    assert "huisdieren" in text.lower()
    assert _documents(deps, "Wie wint het WK voetbal volgend jaar?") == ("", 0)


def test_a_document_is_still_found_by_its_title(deps: SuperAgentDeps) -> None:
    _document(deps.engine, deps.company_id, "Keuringsrapport lift", ["Geen bijzonderheden."])
    text, count = _documents(deps, "keuringsrapport lift")
    assert count >= 1
    assert "Keuringsrapport lift" in text


def test_one_tenants_stored_fact_never_answers_for_another(deps: SuperAgentDeps) -> None:
    facts = {"parties": [], "unit_hint": None, "start_date": None, "end_date": None,
             "key_facts": [{"label": "monthly_rent", "value": "EUR 900"}]}  # fmt: skip
    _document(deps.engine, deps.company_id, "Huurovereenkomst Anna", ["Huurder Anna. De huurprijs is EUR 900."])
    _document(deps.engine, deps.company_id, "Huurovereenkomst Bram", ["Huurder Bram. De huurprijs is EUR 1.400."])
    with Session(deps.engine) as s, s.begin():
        s.execute(update(DocumentRow).where(DocumentRow.title == "Huurovereenkomst Anna").values(facts=facts))
    text, _ = _documents(deps, "How much is the rent of Bram?")
    assert "1.400" in text


def test_a_search_by_date_lists_mail_that_answers_nothing(deps: SuperAgentDeps) -> None:
    _indexed(deps.engine, deps.settings, deps.company_id, "De schilder komt maandag.")
    text, count = _messages_filtered(deps, "new messages", date_from="2026-09-01")
    assert count == 1
    assert "schilder" in text


def test_a_suspicious_document_never_reaches_astra(deps: SuperAgentDeps) -> None:
    _document(deps.engine, deps.company_id, "Keuringsrapport lift", ["De lift is goedgekeurd."])
    with Session(deps.engine) as s, s.begin():
        s.execute(update(DocumentRow).where(DocumentRow.company_id == deps.company_id).values(suspicious=True))
    assert _documents(deps, "keuringsrapport lift") == ("", 0)


def test_each_line_names_its_real_sender(deps: SuperAgentDeps) -> None:
    _indexed(deps.engine, deps.settings, deps.company_id, "Uitleg. " * 120 + "Ik bied 150 euro compensatie.")
    text, _ = _messages(deps, "Welke compensatie is geboden?")
    assert "150 euro" in text
    assert "a@example.test" in text
    assert "inbound" in text

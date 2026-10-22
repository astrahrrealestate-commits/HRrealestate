"""RAG quality gate on the synthetic corpus (offline models): hybrid must beat words alone where it should, never mix
tenants, never use an injected document, and never answer what no document says."""

import pytest
from sqlalchemy import Engine

from app.core.settings import Settings
from app.db.models import Company
from app.llm.embeddings import HashingEmbedder
from evals import rag_eval
from evals.rag_eval import Outcome, Seeded

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake"})


@pytest.fixture
def seeded(migrated_engine: Engine, committed_company: Company) -> Seeded:
    return rag_eval.seed(migrated_engine, HashingEmbedder(), committed_company.id)


@pytest.fixture
def hybrid(migrated_engine: Engine, settings: Settings, seeded: Seeded) -> list[Outcome]:
    return rag_eval.run(migrated_engine, settings, HashingEmbedder(), seeded)


@pytest.fixture
def m10_baseline(migrated_engine: Engine, seeded: Seeded) -> list[Outcome]:
    return rag_eval.run_baseline(migrated_engine, seeded)


def _misses(outcomes: list[Outcome]) -> list[str]:
    return [f"[{o.question.group}] {o.question.text}" for o in outcomes
            if not o.question.real_only and not (o.context_hit or o.fact_ok or o.abstained)]  # fmt: skip


def test_hybrid_scores_clear_the_bar(hybrid: list[Outcome]) -> None:
    scores = rag_eval.score(hybrid)
    assert scores["context_hit"] >= 0.9, _misses(hybrid)
    assert scores["doc_hit"] >= 0.9
    assert scores["mrr"] >= 0.6
    assert scores["fact_accuracy"] == 1.0
    assert scores["abstain_accuracy"] == 1.0


def test_no_tenant_text_and_no_injected_text_ever_reach_the_context(hybrid: list[Outcome]) -> None:
    assert rag_eval.score(hybrid)["isolation_violations"] == 0
    assert [o.question.text for o in hybrid if o.violated] == []


def test_hybrid_is_better_than_the_m10_baseline_across_languages(
    hybrid: list[Outcome], m10_baseline: list[Outcome]
) -> None:
    def hit_rate(outcomes: list[Outcome]) -> float:
        cross = [o for o in outcomes if o.question.group == "cross_language"]
        return sum(o.context_hit for o in cross) / len(cross)

    assert hit_rate(hybrid) > hit_rate(m10_baseline) + 0.3
    assert hit_rate(hybrid) >= 0.9


def test_single_fact_questions_take_the_fact_route_and_conflicts_do_not(hybrid: list[Outcome]) -> None:
    routes = {o.question.text: o.route for o in hybrid}
    assert routes["When does the lease end?"] == "fact"
    assert routes["How much is the rent?"] == "fact"
    assert routes["Hoeveel is de huur?"] != "fact"  # the lease and its addendum disagree


def test_the_conflict_question_sees_the_newer_amount(hybrid: list[Outcome]) -> None:
    [conflict] = [o for o in hybrid if o.question.group == "conflict"]
    assert conflict.context_hit


def test_the_injected_document_is_flagged_and_unanswerable(hybrid: list[Outcome]) -> None:
    [attack] = [o for o in hybrid if o.question.group == "attack"]
    assert attack.abstained
    assert not attack.violated


def test_semantic_questions_are_reported_but_not_asserted_offline(hybrid: list[Outcome]) -> None:
    semantic = [o for o in hybrid if o.question.real_only]
    assert len(semantic) >= 2  # they exist and run; passing them needs a real embedding model

"""Message search quality on the synthetic threads (offline models): the corpus is indexed by the real indexer, scoped
questions never see another person's mail, and every score is computed."""

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.db.models import Company, MessageChunk
from app.llm.embeddings import HashingEmbedder
from evals import message_rag_eval
from evals.message_rag_corpus import QUESTIONS, THREADS
from evals.message_rag_eval import MessageOutcome, SeededThreads

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(test_settings: Settings) -> Settings:
    return test_settings.model_copy(update={"llm_model": "fake", "embedding_model": "fake"})


@pytest.fixture
def seeded(migrated_engine: Engine, settings: Settings, committed_company: Company) -> SeededThreads:
    return message_rag_eval.seed(migrated_engine, settings, committed_company.id)


@pytest.fixture
def outcomes(migrated_engine: Engine, settings: Settings, seeded: SeededThreads) -> list[MessageOutcome]:
    return message_rag_eval.run(migrated_engine, settings, HashingEmbedder(), seeded)


def test_the_corpus_covers_what_the_plan_names() -> None:
    assert len(THREADS) == 12
    assert len(QUESTIONS) == 30
    groups = {q.group for q in QUESTIONS}
    assert {"said", "agreed", "amount", "date", "vendor", "cross_language", "isolation", "abstain"} <= groups
    assert sum(q.group == "abstain" for q in QUESTIONS) == 5


def test_every_thread_is_indexed_through_the_real_indexer(migrated_engine: Engine, seeded: SeededThreads) -> None:
    with Session(migrated_engine) as s:
        threads = s.scalar(
            select(func.count(func.distinct(MessageChunk.thread_ref))).where(
                MessageChunk.company_id == seeded.company_id, MessageChunk.embedding.is_not(None)
            )
        )
    assert threads == len(THREADS)


def test_scoped_questions_never_return_another_persons_mail(outcomes: list[MessageOutcome]) -> None:
    assert [o.question.text for o in outcomes if o.violated] == []
    assert message_rag_eval.score(outcomes)["isolation_violations"] == 0


def test_every_score_is_a_number_in_range(outcomes: list[MessageOutcome]) -> None:
    scores = message_rag_eval.score(outcomes)
    assert set(scores) == {"context_hit", "mrr", "abstain_accuracy", "isolation_violations"}
    assert all(0.0 <= scores[k] <= 1.0 for k in ("context_hit", "mrr", "abstain_accuracy"))

"""Embedders: the deterministic fake behaves like a vector model for tests; the provider wrapper batches."""

import math

import pytest
from pydantic_ai.embeddings import Embedder
from pydantic_ai.embeddings.test import TestEmbeddingModel

from app.core.settings import EMBEDDING_DIMENSIONS, Settings
from app.llm.embeddings import BATCH, HashingEmbedder, ModelEmbedder, build_embedder, to_sql


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_vectors_have_the_column_size_and_unit_length() -> None:
    v = HashingEmbedder().embed_query("De waarborgsom bedraagt twee maanden")
    assert len(v) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)


def test_same_text_same_vector_and_query_equals_document_form() -> None:
    e = HashingEmbedder()
    assert e.embed_query("huur") == e.embed_query("huur") == e.embed_documents(["huur"])[0]


def test_empty_text_is_a_valid_zero_free_vector() -> None:
    v = HashingEmbedder().embed_query("")
    assert len(v) == EMBEDDING_DIMENSIONS
    assert not any(math.isnan(x) for x in v)


def test_related_text_scores_higher_than_unrelated_text() -> None:
    e = HashingEmbedder()
    q = e.embed_query("Hoe hoog is de huur per maand?")
    near = e.embed_documents(["De huur bedraagt EUR 1150 per maand."])[0]
    far = e.embed_documents(["De schilder repareert het dak volgende week."])[0]
    assert cosine(q, near) > cosine(q, far) + 0.2


def test_english_question_finds_the_dutch_passage_through_the_glossary() -> None:
    e = HashingEmbedder()
    q = e.embed_query("What is the deposit?")
    dutch = e.embed_documents(["De waarborgsom is twee maanden kale huur."])[0]
    other = e.embed_documents(["De opzegtermijn is drie maanden."])[0]
    assert cosine(q, dutch) > cosine(q, other)


def test_build_embedder_returns_the_fake_by_default() -> None:
    settings = Settings(database_url="postgresql+psycopg://x@localhost/x", _env_file=None)  # type: ignore[arg-type]
    assert isinstance(build_embedder(settings), HashingEmbedder)


def test_model_embedder_batches_and_returns_lists() -> None:
    calls: list[int] = []

    class Spy(TestEmbeddingModel):
        async def embed(self, inputs, *, input_type, settings=None):  # type: ignore[no-untyped-def]
            calls.append(len(inputs))
            return await super().embed(inputs, input_type=input_type, settings=settings)

    embedder = ModelEmbedder(Embedder(Spy(dimensions=EMBEDDING_DIMENSIONS)))
    got = embedder.embed_documents([f"t{i}" for i in range(BATCH + 5)])
    assert calls == [BATCH, 5]
    assert len(got) == BATCH + 5
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in got)
    assert len(embedder.embed_query("q")) == EMBEDDING_DIMENSIONS


def test_to_sql_is_a_vector_literal() -> None:
    assert to_sql([0.5, -1.0]) == "[0.500000,-1.000000]"


@pytest.mark.parametrize("text", ["x" * 10_000])
def test_very_long_text_is_cut_not_rejected(text: str) -> None:
    assert len(HashingEmbedder().embed_documents([text])[0]) == EMBEDDING_DIMENSIONS


def test_a_hung_provider_times_out_instead_of_holding_the_caller() -> None:
    import asyncio

    class Slow(TestEmbeddingModel):
        async def embed(self, inputs, *, input_type, settings=None):  # type: ignore[no-untyped-def]
            await asyncio.sleep(1.0)
            return await super().embed(inputs, input_type=input_type, settings=settings)

    embedder = ModelEmbedder(Embedder(Slow(dimensions=EMBEDDING_DIMENSIONS)), timeout_sec=0.05)
    with pytest.raises(TimeoutError):
        embedder.embed_query("hello")

"""Text embeddings (ADR 0008): one port, a deterministic fake and the Pydantic AI `Embedder` over OpenAI or Gemini.

Every vector has `EMBEDDING_DIMENSIONS` entries (the `vector` column size). The fake hashes words, with glossary words
of one idea sharing a feature, into a fixed-size unit vector: no network, repeatable, and good enough to show hybrid
retrieval, cross-language matching and ranking in tests. It is not a language model and never stands in for one in
production: boot refuses `embedding_model=fake` in prod.
"""

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from pydantic_ai.embeddings import Embedder, EmbeddingSettings

from app.core.property_terms import canonical_tokens
from app.core.settings import EMBEDDING_DIMENSIONS, Settings

BATCH = 64
MAX_CHARS = 6000  # about 1,500 tokens: far above a chunk, keeps one oversized text from failing a batch


class TextEmbedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Repeatable word-count vectors: each idea lands in one hashed slot, then the vector is scaled to unit length."""

    def _vector(self, text: str) -> list[float]:
        counts = Counter(canonical_tokens(text))
        vec = [0.0] * EMBEDDING_DIMENSIONS
        for token, n in counts.items():
            digest = hashlib.sha1(token.encode(), usedforsecurity=False).digest()
            slot = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            vec[slot] += (1.0 if digest[4] & 1 else -1.0) * (1.0 + math.log(n))
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t[:MAX_CHARS]) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text[:MAX_CHARS])


class ModelEmbedder:
    """Provider embeddings through Pydantic AI, in batches; transient errors propagate for the step to retry."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._settings = EmbeddingSettings(dimensions=EMBEDDING_DIMENSIONS)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = [t[:MAX_CHARS] for t in texts[start : start + BATCH]]
            out.extend(list(v) for v in self._embedder.embed_documents_sync(batch, settings=self._settings).embeddings)
        return out

    def embed_query(self, text: str) -> list[float]:
        return list(self._embedder.embed_query_sync(text[:MAX_CHARS], settings=self._settings).embeddings[0])


def build_embedder(settings: Settings) -> TextEmbedder:
    provider, _, name = settings.embedding_model.partition(":")
    if settings.embedding_model == "fake":
        return HashingEmbedder()
    if provider == "openai":
        from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
        from pydantic_ai.providers.openai import OpenAIProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return ModelEmbedder(Embedder(OpenAIEmbeddingModel(name, provider=OpenAIProvider(api_key=key))))
    if provider == "google-gla":
        from pydantic_ai.embeddings.google import GoogleEmbeddingModel
        from pydantic_ai.providers.google import GoogleProvider

        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        return ModelEmbedder(Embedder(GoogleEmbeddingModel(name, provider=GoogleProvider(api_key=key))))
    return ModelEmbedder(Embedder(settings.embedding_model))


def to_sql(vector: Sequence[float]) -> str:
    """A pgvector literal for a bound parameter (`'[0.1,0.2]'::vector`)."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"

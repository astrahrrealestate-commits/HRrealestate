"""Text embeddings (ADR 0008): one port, a deterministic fake and the Pydantic AI `Embedder` over OpenAI or Gemini.

Every vector has `EMBEDDING_DIMENSIONS` entries (the `vector` column size). The fake hashes words, with glossary words
of one idea sharing a feature, into a fixed-size unit vector: no network, repeatable, and good enough to show hybrid
retrieval, cross-language matching and ranking in tests. It is not a language model and never stands in for one in
production: boot refuses `embedding_model=fake` in prod.
"""

import asyncio
import hashlib
import math
import threading
from collections import Counter
from collections.abc import Coroutine, Sequence
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Protocol

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


_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def _run_loop(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
    asyncio.set_event_loop(loop)
    ready.set()
    loop.run_forever()


def _embed_loop() -> asyncio.AbstractEventLoop:
    """One dedicated asyncio loop for all provider embedding calls: httpx.AsyncClient pools keep-alive sockets on
    the loop that opened them, so running calls across worker threads raises 'bound to a different event loop'."""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None:
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            threading.Thread(target=_run_loop, args=(loop, ready), name="embed-loop", daemon=True).start()
            ready.wait()
            _LOOP = loop
        return _LOOP


class ModelEmbedder:
    """Provider embeddings through Pydantic AI, in batches. Every call has a deadline (`TimeoutError`, which callers
    treat as transient): a hung provider must not hold a database session or a workflow step for minutes."""

    def __init__(self, embedder: Embedder, timeout_sec: float = 30.0) -> None:
        self._embedder = embedder
        self._timeout = timeout_sec
        self._settings = EmbeddingSettings(dimensions=EMBEDDING_DIMENSIONS)

    def _within_deadline(self, coro: Coroutine[Any, Any, list[list[float]]]) -> list[list[float]]:
        try:
            loop = _embed_loop()
            future = asyncio.run_coroutine_threadsafe(asyncio.wait_for(coro, timeout=self._timeout), loop)
        except Exception:
            coro.close()
            raise
        try:
            return future.result(timeout=self._timeout + 1.0)
        except FutureTimeoutError as exc:
            future.cancel()
            raise TimeoutError from exc

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            batch = [t[:MAX_CHARS] for t in texts[start : start + BATCH]]
            out.extend(self._within_deadline(self._embed(batch)))
        return out

    async def _embed(self, batch: list[str]) -> list[list[float]]:
        res = await self._embedder.embed_documents(batch, settings=self._settings)
        return [list(v) for v in res.embeddings]

    def embed_query(self, text: str) -> list[float]:
        """A question, not a passage: providers embed the two differently. Never use it for text that is stored."""
        return self._within_deadline(self._embed_question(text[:MAX_CHARS]))[0]

    async def _embed_question(self, text: str) -> list[list[float]]:
        res = await self._embedder.embed_query(text, settings=self._settings)
        return [list(v) for v in res.embeddings]


def build_embedder(settings: Settings) -> TextEmbedder:
    provider, _, name = settings.embedding_model.partition(":")
    if settings.embedding_model == "fake":
        return HashingEmbedder()
    if provider == "openai":
        from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
        from pydantic_ai.providers.openai import OpenAIProvider

        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        return ModelEmbedder(
            Embedder(OpenAIEmbeddingModel(name, provider=OpenAIProvider(api_key=key))), settings.llm_timeout_sec
        )
    if provider == "google-gla":
        from pydantic_ai.embeddings.google import GoogleEmbeddingModel

        from app.llm.runtime import gemini_provider

        key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        return ModelEmbedder(
            Embedder(GoogleEmbeddingModel(name, provider=gemini_provider(key))), settings.llm_timeout_sec
        )
    return ModelEmbedder(Embedder(settings.embedding_model), settings.llm_timeout_sec)


def to_sql(vector: Sequence[float]) -> str:
    """A pgvector literal for a bound parameter (`'[0.1,0.2]'::vector`)."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"

"""CTranslate2 adapter for the Helsinki-NLP OPUS-MT Dutch to English model (Marian, int8 on CPU)."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.errors import TranslationUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)

Loader = Callable[[], tuple[Any, Any, Any]]  # (ctranslate2.Translator, source SentencePiece, target SentencePiece)

_EOS = "</s>"  # the converted model does not add it itself (add_source_eos is false)


class Ct2Translator:
    engine = "opus-mt-nl-en"

    def __init__(self, model_dir: Path, *, threads: int = 2, beam_size: int = 4, loader: Loader | None = None) -> None:
        self._dir = model_dir
        self._threads = threads
        self._beam = beam_size
        self._loader = loader or self._load_from_disk
        self._parts: tuple[Any, Any, Any] | None = None
        self._lock = threading.Lock()

    def translate(self, segments: list[str]) -> list[str]:
        if not segments:
            return []
        model, source, target = self._ready()
        batch = [[*source.encode(s, out_type=str), _EOS] for s in segments]
        longest = max(len(tokens) for tokens in batch)
        results = model.translate_batch(
            batch, beam_size=self._beam, max_batch_size=32, max_decoding_length=min(256, 2 * longest + 16)
        )
        return [str(target.decode(r.hypotheses[0])) for r in results]

    def _ready(self) -> tuple[Any, Any, Any]:
        with self._lock:  # load once; translate_batch itself is thread-safe
            if self._parts is None:
                try:
                    self._parts = self._loader()
                except TranslationUnavailableError:
                    raise
                except (
                    Exception
                ) as exc:  # corrupt model file, missing native library: one clear 503, not a 500 each time
                    log.error("translation.load_failed", error=type(exc).__name__)
                    raise TranslationUnavailableError("translation model could not be loaded") from exc
            return self._parts

    def _load_from_disk(self) -> tuple[Any, Any, Any]:
        if not (self._dir / "model.bin").is_file():
            raise TranslationUnavailableError(f"translation model not found in {self._dir} (make translation-model)")
        import ctranslate2
        import sentencepiece

        model = ctranslate2.Translator(
            str(self._dir), device="cpu", compute_type="int8", inter_threads=1, intra_threads=self._threads
        )
        source = sentencepiece.SentencePieceProcessor(model_file=str(self._dir / "source.spm"))
        target = sentencepiece.SentencePieceProcessor(model_file=str(self._dir / "target.spm"))
        return model, source, target

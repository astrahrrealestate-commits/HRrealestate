"""The CTranslate2 adapter: lazy load, Marian end-of-sentence token, SentencePiece in and out. Model faked."""

from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from app.core.errors import TranslationUnavailableError
from app.translation.ct2 import Ct2Translator


class FakeSp:
    def encode(self, text: str, out_type: type = str) -> list[str]:
        return text.split()

    def decode(self, pieces: list[str]) -> str:
        return " ".join(pieces)


class FakeHypothesis:
    def __init__(self, tokens: list[str]) -> None:
        self.hypotheses = [tokens]


class FakeCt2:
    def __init__(self) -> None:
        self.batches: list[list[list[str]]] = []
        self.options: dict[str, Any] = {}

    def translate_batch(self, batch: list[list[str]], **kw: Any) -> list[FakeHypothesis]:
        self.options = kw
        self.batches.append(batch)
        return [FakeHypothesis([t.upper() for t in src if t != "</s>"]) for src in batch]


def make(loads: list[int]) -> tuple[Ct2Translator, FakeCt2]:
    ct2 = FakeCt2()

    def loader() -> tuple[Any, Any, Any]:
        loads.append(1)
        return ct2, FakeSp(), FakeSp()

    return Ct2Translator(Path("/unused"), loader=loader), ct2


def test_translate_encodes_adds_eos_and_decodes() -> None:
    tr, ct2 = make([])
    assert tr.translate(["goede morgen", "hallo"]) == ["GOEDE MORGEN", "HALLO"]
    assert ct2.batches == [[["goede", "morgen", "</s>"], ["hallo", "</s>"]]]


def test_model_loads_once_on_first_use_even_from_many_threads() -> None:
    loads: list[int] = []
    tr, _ = make(loads)
    assert loads == []
    threads = [Thread(target=tr.translate, args=(["a"],)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert loads == [1]


def test_empty_batch_does_not_load_the_model() -> None:
    loads: list[int] = []
    tr, _ = make(loads)
    assert tr.translate([]) == []
    assert loads == []


def test_missing_model_directory_is_translation_unavailable(tmp_path: Path) -> None:
    tr = Ct2Translator(tmp_path / "nope")
    with pytest.raises(TranslationUnavailableError, match="model"):
        tr.translate(["hallo"])


def test_batches_and_output_length_are_bounded() -> None:
    tr, ct2 = make([])
    tr.translate(["een twee drie"])
    assert ct2.options["max_batch_size"] == 32
    assert ct2.options["max_decoding_length"] == 2 * 4 + 16  # twice the source tokens (3 + EOS), plus slack


def test_a_model_that_cannot_load_is_translation_unavailable_not_a_500() -> None:
    def broken() -> tuple[Any, Any, Any]:
        raise RuntimeError("bad model.bin")

    with pytest.raises(TranslationUnavailableError, match="could not be loaded"):
        Ct2Translator(Path("/unused"), loader=broken).translate(["hallo"])

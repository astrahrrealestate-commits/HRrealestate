import hashlib
from pathlib import Path

import pytest

from app.contracts import PromptRef
from app.core.errors import PromptNotFoundError
from app.llm import prompts


def test_load_prompt_hashes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "demo.md").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    prompts.load_prompt.cache_clear()
    loaded = prompts.load_prompt(PromptRef(name="demo", version="v1"))
    assert loaded.text == "hello"
    assert loaded.sha256 == hashlib.sha256(b"hello").hexdigest()


def test_missing_prompt_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts, "PROMPTS_DIR", tmp_path)
    prompts.load_prompt.cache_clear()
    with pytest.raises(PromptNotFoundError):
        prompts.load_prompt(PromptRef(name="nope", version="v9"))

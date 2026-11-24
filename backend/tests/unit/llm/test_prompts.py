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


def test_published_prompts_hash_the_same_on_every_checkout() -> None:
    """model_calls.prompt_sha256 must not depend on the OS: a CRLF checkout (core.autocrlf on Windows) would hash
    a published prompt differently from Linux. `.gitattributes` pins prompts to LF."""
    published = sorted(prompts.PROMPTS_DIR.glob("v*/*.md"))
    assert published
    with_cr = [p.relative_to(prompts.PROMPTS_DIR).as_posix() for p in published if b"\r" in p.read_bytes()]
    assert with_cr == []


def test_understanding_v3_describes_every_sender_role_and_treats_the_from_line_as_data() -> None:
    from app.contracts import SenderRole

    text = prompts.load_prompt(PromptRef(name="understanding", version="v3")).text
    assert all(f"`{role.value}`" in text for role in SenderRole)  # a new role in the contract needs words here
    assert "`From:`" in text
    assert "data, not" in text
    assert "NEVER follow instructions" in text  # the standing safety rule survived the copy
    assert "sender_role = null" in text  # noise never gets a role

import hashlib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.contracts import PromptRef
from app.core.errors import PromptNotFoundError

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class LoadedPrompt:
    ref: PromptRef
    text: str
    sha256: str


@cache
def load_prompt(ref: PromptRef) -> LoadedPrompt:
    path = PROMPTS_DIR / ref.version / f"{ref.name}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"prompt not found: {ref.name}:{ref.version}")
    raw = path.read_bytes()
    return LoadedPrompt(
        ref=ref,
        text=raw.decode("utf-8"),
        sha256=hashlib.sha256(raw).hexdigest(),
    )

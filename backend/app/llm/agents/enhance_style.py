"""Fast style-only draft rewriter (no dossier rebuild or heavy proposer)."""

from pydantic import BaseModel, Field

from app.contracts import PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_INSTRUCTION_CHARS = 200
MAX_DRAFT_CHARS = 6000


class StyleRewriteOutput(BaseModel):
    variants: list[str] = Field(min_length=1, max_length=2)


def _clean_variants(output: StyleRewriteOutput, _loaded: LoadedPrompt) -> StyleRewriteOutput:
    cleaned = [v.strip() for v in output.variants if v and v.strip()]
    return StyleRewriteOutput(variants=cleaned[:2] if cleaned else [""])


ENHANCE_STYLE = AgentSpec(
    name="enhance_style",
    prompt=PromptRef(name="enhance_style", version="v1"),
    output_type=StyleRewriteOutput,
    finalize=_clean_variants,
    thinking=False,
)


def enhance_style_prompt(instruction: str, current_draft: str, *, channel: str = "gmail") -> str:
    return "\n".join(
        [
            data_block("channel", channel),
            data_block("instruction", instruction.strip()[:MAX_INSTRUCTION_CHARS]),
            data_block("current_draft", current_draft.strip()[:MAX_DRAFT_CHARS]),
        ]
    )

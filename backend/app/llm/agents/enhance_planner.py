"""Fast retrieval-gap planner for instruction-aware draft enhancement."""

from collections.abc import Sequence

from app.contracts import PromptRef
from app.contracts.enhance import EnhancePlan
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_INSTRUCTION_CHARS = 500
MAX_DRAFT_CHARS = 2500
MAX_SUMMARY_CHARS = 1500


def _unchanged(output: EnhancePlan, _loaded: LoadedPrompt) -> EnhancePlan:
    return output


ENHANCE_PLANNER = AgentSpec(
    name="enhance_planner",
    prompt=PromptRef(name="enhance_planner", version="v1"),
    output_type=EnhancePlan,
    finalize=_unchanged,
    thinking=False,
)


def enhance_planner_prompt(
    instruction: str,
    current_draft: str,
    *,
    case_summary: str,
    category: str,
    loaded_sources: Sequence[str] = (),
) -> str:
    sources_line = ", ".join(loaded_sources[:12]) or "none"
    summary = (
        f"Category: {category}\n"
        f"Case summary: {(case_summary or 'none').strip()[:MAX_SUMMARY_CHARS]}\n"
        f"Already loaded sources: {sources_line}"
    )
    return "\n".join(
        [
            data_block("instruction", instruction.strip()[:MAX_INSTRUCTION_CHARS]),
            data_block("current_draft", current_draft.strip()[:MAX_DRAFT_CHARS] or "none"),
            data_block("dossier_summary", summary),
        ]
    )

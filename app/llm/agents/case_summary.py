"""Case summary agent specification."""

from app.contracts import CaseSummary, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt


def _stamp_prompt_version(output: CaseSummary, _loaded: LoadedPrompt) -> CaseSummary:
    return output


CASE_SUMMARY = AgentSpec(
    name="case_summary",
    prompt=PromptRef(name="case_summary", version="v1"),
    output_type=CaseSummary,
    finalize=_stamp_prompt_version,
)

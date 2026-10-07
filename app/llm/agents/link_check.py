"""Link check agent specification."""

from app.contracts import LinkDecision, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt


def _stamp_prompt_version(output: LinkDecision, _loaded: LoadedPrompt) -> LinkDecision:
    return output


LINK_CHECK = AgentSpec(
    name="link_check",
    prompt=PromptRef(name="link_check", version="v1"),
    output_type=LinkDecision,
    finalize=_stamp_prompt_version,
)

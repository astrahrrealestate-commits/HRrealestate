"""Job items agent (M11): what the work is, in priceable lines, from the case summary and its messages.

Tenant, vendor and case text is untrusted data (invariant 6); the agent has no write tools and reads no prices.
"""

from collections.abc import Sequence

from app.contracts import JobItems, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_MESSAGES = 10
MAX_CASE_CHARS = 1200


def _unchanged(output: JobItems, _loaded: LoadedPrompt) -> JobItems:
    return output


JOB_ITEMS = AgentSpec(
    name="job_items", prompt=PromptRef(name="job_items", version="v1"), output_type=JobItems, finalize=_unchanged
)


def job_items_prompt(case_summary: str, message_texts: Sequence[str]) -> str:
    case = data_block("case", case_summary.strip() or "none", MAX_CASE_CHARS)
    messages = [data_block("message", t.strip() or "none") for t in message_texts[-MAX_MESSAGES:]]
    return "\n".join([case, *(messages or [data_block("message", "none")])])

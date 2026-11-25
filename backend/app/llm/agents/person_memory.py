"""Person memory agent (M13): the rolling memory of one contact, written from their own mail only."""

from collections.abc import Sequence

from app.contracts import PromptRef
from app.contracts.person_memory import PersonMemory
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_THREAD_CHARS = 40_000
MAX_CASES_CHARS = 6_000


def _unchanged(output: PersonMemory, _loaded: LoadedPrompt) -> PersonMemory:
    return output


PERSON_MEMORY = AgentSpec(
    name="person_memory",
    prompt=PromptRef(name="person_memory", version="v1"),
    output_type=PersonMemory,
    finalize=_unchanged,
    redact_output=True,  # stored on the profile, which erasure deletes; the call log keeps only its size
)


def person_memory_prompt(lines: Sequence[str], case_summaries: Sequence[str]) -> str:
    """`lines`: the person's mail and what was sent to them, newest first, so a cap drops the oldest."""
    return "\n".join(
        [
            data_block("case", "\n".join(case_summaries) or "none", MAX_CASES_CHARS),
            data_block("thread", "\n\n".join(lines) or "none", MAX_THREAD_CHARS),
        ]
    )

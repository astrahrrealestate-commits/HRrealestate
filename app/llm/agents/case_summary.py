"""Case summary agent (#3): the rolling English summary of a case and its next step, for Harjot."""

from collections.abc import Sequence
from datetime import datetime

from app.contracts import CaseSummary, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block


def _unchanged(output: CaseSummary, _loaded: LoadedPrompt) -> CaseSummary:
    return output


CASE_SUMMARY = AgentSpec(
    name="case_summary",
    prompt=PromptRef(name="case_summary", version="v2"),
    output_type=CaseSummary,
    finalize=_unchanged,
)


def case_summary_prompt(previous_summary: str, new_messages: Sequence[tuple[datetime, str, str]]) -> str:
    """`new_messages`: (sent_at, sender label, text), oldest first. Each message gets its own <message> block."""
    blocks = [data_block("message", f"{at.isoformat()} {sender}:\n{text}") for at, sender, text in new_messages]
    return "\n".join([data_block("data", previous_summary.strip() or "none"), *blocks])

"""Link check agent (#3): does a message continue one of the sender's open cases? Used only for ambiguous cases."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.contracts import Category, LinkDecision, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block, escape

MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class CandidateCase:
    case_id: UUID
    category: Category
    summary: str
    last_message_at: datetime | None


def _unchanged(output: LinkDecision, _loaded: LoadedPrompt) -> LinkDecision:
    return output


LINK_CHECK = AgentSpec(
    name="link_check",
    prompt=PromptRef(name="link_check", version="v2"),
    output_type=LinkDecision,
    finalize=_unchanged,
)


def _candidate(c: CandidateCase) -> str:
    when = c.last_message_at.isoformat() if c.last_message_at else "never"
    summary = " ".join(c.summary.split())[:400] or "(no summary yet)"
    return f"candidate: {c.case_id} | {c.category.value} | {when}\n  {summary}"


def link_check_prompt(message_text: str, category: Category, candidates: Sequence[CandidateCase]) -> str:
    """Case summaries derive from tenant text, so they sit inside the untrusted <data> block too."""
    listing = "\n".join(escape(_candidate(c), "data") for c in candidates)
    return f"Message category: {category.value}\n{data_block('data', listing)}\n{data_block('message', message_text)}"


def accept_link(decision: LinkDecision, candidates: Sequence[CandidateCase]) -> UUID | None:
    """Code-side check (invariant 6): only a listed candidate, only when the model is reasonably sure."""
    if decision.case_id is None or decision.confidence < MIN_CONFIDENCE:
        return None
    return decision.case_id if decision.case_id in {c.case_id for c in candidates} else None

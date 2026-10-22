"""Concierge (Super Agent) planner: turns an owner message into a ConciergePlan. No tools; the executor validates."""

from collections.abc import Sequence

from app.contracts import ConciergePlan, PromptRef
from app.llm.agents.owner_qa import CaseBrief
from app.llm.calls import AgentSpec
from app.llm.page_blocks import page_blocks
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

# v3 adds the plan's own `reply` (single-call answers); v2 (page blocks) and v1 stay published and loadable (evals:
# version=v2 / version=v1).
PROMPT_VERSION = "v3"
MAX_HISTORY = 12  # lines: `owner:` and `assistant:` for each of 6 turns
MAX_HISTORY_LINE = 420  # an `owner: ` prefix plus 400 characters


def _unchanged(output: ConciergePlan, _loaded: LoadedPrompt) -> ConciergePlan:
    return output


CONCIERGE = AgentSpec(
    name="concierge",
    prompt=PromptRef(name="concierge", version=PROMPT_VERSION),
    output_type=ConciergePlan,
    finalize=_unchanged,
)


def concierge_prompt(
    question: str,
    recent: Sequence[str],
    cases: Sequence[CaseBrief],
    open_tasks: Sequence[str],
    page_facts_text: str = "",
    snapshot: str = "",
    filters: str = "",
) -> str:
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    history = "\n".join(" ".join(r.split())[:MAX_HISTORY_LINE] for r in recent[-MAX_HISTORY:]) or "no earlier messages"
    page = page_blocks(page_facts_text, snapshot, filters)
    return "\n".join([data_block("data", data), data_block("history", history), *page, data_block("message", question)])

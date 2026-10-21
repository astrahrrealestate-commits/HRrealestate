"""Concierge (Super Agent) planner: turns an owner message into a ConciergePlan. No tools; the executor validates."""

from collections.abc import Sequence

from app.contracts import ConciergePlan, PromptRef
from app.llm.agents.owner_qa import CaseBrief
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

PROMPT_VERSION = "v2"  # v2 adds the page blocks; v1 stays published and loadable (evals: version=v1)
MAX_HISTORY = 12  # lines: `owner:` and `assistant:` for each of 6 turns
MAX_HISTORY_LINE = 420  # an `owner: ` prefix plus 400 characters
MAX_SNAPSHOT = 6000  # the page snapshot block (the request contract enforces the same limit)


def _unchanged(output: ConciergePlan, _loaded: LoadedPrompt) -> ConciergePlan:
    return output


CONCIERGE = AgentSpec(
    name="concierge",
    prompt=PromptRef(name="concierge", version=PROMPT_VERSION),
    output_type=ConciergePlan,
    finalize=_unchanged,
)


def _page_blocks(page_facts_text: str, snapshot: str) -> list[str]:
    """Server facts (authoritative) and the browser's snapshot (unverified): both escaped data blocks, never
    instructions. An absent page adds nothing, so a page-less prompt is unchanged."""
    blocks = [data_block("page_facts", page_facts_text)] if page_facts_text.strip() else []
    if snapshot.strip():
        blocks.append(data_block("page_snapshot", snapshot[:MAX_SNAPSHOT]))
    return blocks


def concierge_prompt(
    question: str,
    recent: Sequence[str],
    cases: Sequence[CaseBrief],
    open_tasks: Sequence[str],
    page_facts_text: str = "",
    snapshot: str = "",
) -> str:
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    history = "\n".join(" ".join(r.split())[:MAX_HISTORY_LINE] for r in recent[-MAX_HISTORY:]) or "no earlier messages"
    blocks = [data_block("data", data), data_block("history", history), *_page_blocks(page_facts_text, snapshot)]
    return "\n".join([*blocks, data_block("message", question)])

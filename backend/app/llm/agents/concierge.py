"""Concierge (Super Agent) planner: turns an owner message into a ConciergePlan. No tools; the executor validates."""

from collections.abc import Sequence

from app.contracts import ConciergePlan, PromptRef
from app.llm.agents.owner_qa import CaseBrief
from app.llm.calls import AgentSpec
from app.llm.page_blocks import page_blocks
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

# v3 adds the plan's own `reply` (single-call answers), v4 the document intents, v5 lets `reply` carry amounts found in
# `<data>`/`<page_facts>`, v7 `needs_research` and a conversational `reply`, v8 the `remember`, `calendar` and
# `rent_status` intents, redrafts ("make it shorter") as `draft_reply`, and the negation, word and several-requests
# rules, v9 the Astra persona, no placeholder `calendar` steps, database-vs-document routing and directory lookups;
# v1-v8 stay published and loadable (evals: version=vN).
PROMPT_VERSION = "v9"
NAMED_BLOCKS = int(PROMPT_VERSION.removeprefix("v")) >= 10  # v10 reads <entities> and <conversation>
MAX_HISTORY = 24  # lines: `owner:` and `assistant:` for each of 12 turns
MAX_HISTORY_LINE = 1220  # an `owner: ` prefix plus 1,200 characters
SUMMARY_CHARS = 1200


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
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:SUMMARY_CHARS]}"
        for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    history = "\n".join(" ".join(r.split())[:MAX_HISTORY_LINE] for r in recent[-MAX_HISTORY:]) or "no earlier messages"
    page = page_blocks(page_facts_text, snapshot, filters)
    return "\n".join([data_block("data", data), data_block("history", history), *page, data_block("message", question)])

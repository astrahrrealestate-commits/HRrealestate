"""Concierge (Super Agent) planner: turns an owner message into a ConciergePlan. No tools; the executor validates."""

from collections.abc import Sequence

from app.contracts import ConciergePlan, PromptRef
from app.llm.agents.owner_qa import CaseBrief
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

MAX_HISTORY = 6


def _unchanged(output: ConciergePlan, _loaded: LoadedPrompt) -> ConciergePlan:
    return output


CONCIERGE = AgentSpec(
    name="concierge", prompt=PromptRef(name="concierge", version="v1"), output_type=ConciergePlan, finalize=_unchanged
)


def concierge_prompt(
    question: str, recent: Sequence[str], cases: Sequence[CaseBrief], open_tasks: Sequence[str]
) -> str:
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    history = "\n".join(" ".join(r.split())[:400] for r in recent[-MAX_HISTORY:]) or "no earlier messages"
    return f"{data_block('data', data)}\n{data_block('history', history)}\n{data_block('message', question)}"

"""Owner Q&A agent (preview of #10 Super Agent): read-only answers about open cases and tasks. No tools."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.contracts import OwnerAnswer, PromptRef
from app.llm.calls import AgentSpec
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

FALLBACK_ANSWER = "Sorry, I could not answer that right now. Try `tasks` or `waiting`, or ask again later."


@dataclass(frozen=True)
class CaseBrief:
    case_id: UUID
    label: str
    state: str
    urgency: str
    summary: str


def _unchanged(output: OwnerAnswer, _loaded: LoadedPrompt) -> OwnerAnswer:
    return output


OWNER_QA = AgentSpec(
    name="owner_qa", prompt=PromptRef(name="owner_qa", version="v1"), output_type=OwnerAnswer, finalize=_unchanged
)


def owner_qa_prompt(question: str, cases: Sequence[CaseBrief], open_tasks: Sequence[str]) -> str:
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    return f"{data_block('data', data)}\n{data_block('message', question)}"


def accept_refs(answer: OwnerAnswer, cases: Sequence[CaseBrief]) -> OwnerAnswer:
    known = {c.case_id for c in cases}
    return answer.model_copy(update={"case_refs": [r for r in answer.case_refs if r in known]})

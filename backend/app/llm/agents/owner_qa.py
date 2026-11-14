"""Owner Q&A agent (preview of #10 Super Agent): read-only answers about open cases and tasks. No tools.

On a dashboard page (the Super Agent's `answer` step) the prompt adds the escaped `<page_facts>` (authoritative) and
`<page_snapshot>` (unverified) blocks and uses prompt v3; without a page the prompt and spec (v2) are unchanged.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from app.contracts import OwnerAnswer, PromptRef
from app.llm.calls import AgentSpec
from app.llm.page_blocks import PagePrompt, page_blocks
from app.llm.prompts import LoadedPrompt
from app.llm.render import data_block

FALLBACK_ANSWER = "Sorry, I could not answer that right now. Try `tasks` or `waiting`, or ask again later."


REFUSAL_ANSWER = "I only answer questions about your cases and tasks. Try `tasks` or `waiting`, or send `help`."


def answer_text(answer: OwnerAnswer) -> str:
    """What Harjot sees: the model's answer only when the question was in scope; a fixed refusal otherwise."""
    return answer.answer if answer.in_scope else REFUSAL_ANSWER


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
    name="owner_qa", prompt=PromptRef(name="owner_qa", version="v2"), output_type=OwnerAnswer, finalize=_unchanged
)
OWNER_QA_PAGE = AgentSpec(  # v3: the page rules; used only when the question comes with a dashboard page
    name="owner_qa", prompt=PromptRef(name="owner_qa", version="v3"), output_type=OwnerAnswer, finalize=_unchanged
)

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Server-built fact lines only (page_facts.facts_text): stored text sits on indented lines and cannot match these.
_PAGE_CASE_LINES = re.compile(
    rf"^open case: ({_UUID}) \|"
    rf"|^open (?:thread|approval): [^\n]* \| case ({_UUID})$"
    rf"|^- case ({_UUID}) \|"
    rf"|^- approval {_UUID} \| \w+ \| \w+ \| case ({_UUID})$",
    re.M,
)


def owner_qa_spec(page: PagePrompt) -> AgentSpec[OwnerAnswer]:
    """v3 when a page is present, else v2 (WhatsApp/Chat questions and page-less agent turns are unchanged)."""
    return OWNER_QA_PAGE if page.present else OWNER_QA


def owner_qa_prompt(
    question: str,
    cases: Sequence[CaseBrief],
    open_tasks: Sequence[str],
    *,
    page_facts_text: str = "",
    snapshot: str = "",
    filters: str = "",
) -> str:
    """Data, then the page blocks (only when non-empty), then the question. Without a page it is byte-identical to the
    v2-era prompt."""
    lines = [
        f"case: {c.case_id} | {c.label} | {c.state} | {c.urgency}\n  {' '.join(c.summary.split())[:400]}" for c in cases
    ]
    tasks = [f"task: {t}" for t in open_tasks]
    data = "\n".join([*lines, *tasks]) or "no open cases or tasks"
    page = page_blocks(page_facts_text, snapshot, filters)
    return "\n".join([data_block("data", data), *page, data_block("message", question)])


def page_case_ids(page_facts_text: str) -> set[UUID]:
    """Case ids on the server-built fact lines (the open case, the open thread's or approval's case, visible case and
    approval rows). These were resolved company-scoped; ids in stored text or the snapshot never count."""
    return {UUID(next(g for g in m.groups() if g)) for m in _PAGE_CASE_LINES.finditer(page_facts_text)}


def accept_refs(answer: OwnerAnswer, cases: Sequence[CaseBrief], page_ids: Collection[UUID] = ()) -> OwnerAnswer:
    """Only case ids the model was shown as company data: the brief's cases and the page's resolved case ids."""
    known = {c.case_id for c in cases} | set(page_ids)
    return answer.model_copy(update={"case_refs": [r for r in answer.case_refs if r in known]})

"""The owner question path with and without a dashboard page (database and model patched out)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.contracts import OwnerAnswer
from app.core.errors import AgentFailedError, BudgetExceededError
from app.llm.agents.owner_qa import FALLBACK_ANSWER, OWNER_QA, OWNER_QA_PAGE, CaseBrief, accept_refs, owner_qa_prompt
from app.llm.budget import OWNER_QA_PURPOSE
from app.llm.calls import CallResult
from app.llm.page_blocks import PagePrompt
from app.pipeline import owner_commands as oc

M = "app.pipeline.owner_commands"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
PAGE_CASE = UUID(int=3)
PAGE = PagePrompt(
    f"view: approvals\nopen case: {PAGE_CASE} | Joris · maintenance | open | urgency normal",
    "Approvals\n" + "x" * 5000,
    "filters: status=pending",
)
ANSWER = OwnerAnswer(in_scope=True, refusal_reason=None, answer="The draft is fine.", case_refs=[PAGE_CASE, uuid4()])


@pytest.fixture
def agent() -> Iterator[MagicMock]:
    with (
        patch(f"{M}.Session", MagicMock()),
        patch(f"{M}.work_repo.open_tasks", return_value=[]),
        patch(f"{M}.run_agent", return_value=CallResult(output=ANSWER, model_call_id=uuid4())) as run,
    ):
        yield run


def _ask(text: str, page: PagePrompt | None = None) -> str:
    cmd = oc.Command(oc.CommandKind.question, text=text)
    if page is None:  # the WhatsApp/Chat call shape: no page argument at all
        return oc.run_command(MagicMock(), MagicMock(), uuid4(), cmd, now=NOW)
    return oc.run_command(MagicMock(), MagicMock(), uuid4(), cmd, now=NOW, page=page)


def test_without_a_page_spec_and_prompt_are_unchanged(agent: MagicMock) -> None:
    assert _ask("what is open?") == "The draft is fine."
    spec, prompt, ctx = agent.call_args.args[2:5]
    assert spec is OWNER_QA
    assert prompt == owner_qa_prompt("what is open?", [], [])
    assert ctx.purpose == OWNER_QA_PURPOSE


def test_with_a_page_v3_sees_facts_filters_and_snapshot(agent: MagicMock) -> None:
    _ask("is this draft okay?", page=PAGE)
    spec, prompt, ctx = agent.call_args.args[2:5]
    assert spec is OWNER_QA_PAGE
    assert f"<page_facts>\n{PAGE.facts}\n</page_facts>" in prompt
    assert f"<page_snapshot>\n{PAGE.filters}\n{PAGE.snapshot}\n</page_snapshot>" in prompt
    assert ctx.purpose == OWNER_QA_PURPOSE


def test_screening_applies_to_the_owner_text_only(agent: MagicMock) -> None:
    assert _ask("🙂🙂", page=PAGE) == oc.NOT_A_QUESTION
    assert _ask("a" * (oc.MAX_QUESTION_CHARS + 1), page=PAGE) == oc.TOO_LONG
    agent.assert_not_called()
    assert _ask("summarise this", page=PAGE) == "The draft is fine."  # a 5000-char snapshot is not "too long"


def test_page_case_ids_pass_the_ref_check(agent: MagicMock) -> None:
    kept: list[OwnerAnswer] = []

    def spy(answer: OwnerAnswer, cases: list[CaseBrief], page_ids: set[UUID]) -> OwnerAnswer:
        kept.append(accept_refs(answer, cases, page_ids))
        return kept[-1]

    with patch(f"{M}.accept_refs", side_effect=spy) as accept:
        _ask("is this draft okay?", page=PAGE)
    assert accept.call_args.args[2] == {PAGE_CASE}
    assert [k.case_refs for k in kept] == [[PAGE_CASE]]


@pytest.mark.parametrize(
    ("error", "expected"),
    [(BudgetExceededError("owner_qa_daily_calls"), oc.LIMIT_ANSWER), (AgentFailedError("boom"), FALLBACK_ANSWER)],
)
def test_fallbacks_are_unchanged_on_a_page(agent: MagicMock, error: Exception, expected: str) -> None:
    agent.side_effect = error
    assert _ask("is this draft okay?", page=PAGE) == expected

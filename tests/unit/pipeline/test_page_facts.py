"""Page facts: pure rendering, caps, and what is dropped (kinds only, never the ids the client sent)."""

from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from app.contracts import Channel, PageContext
from app.contracts.thread_key import encode_thread_key
from app.pipeline import page_facts as pf
from app.pipeline.page_facts import (
    ApprovalFact,
    CaseFact,
    DocumentFact,
    MessageFact,
    PageFacts,
    TaskFact,
    ThreadFact,
    facts_text,
    one_line,
)

CASE = UUID(int=7)
KEY = encode_thread_key(Channel.gmail, "<t1@mail.test>")
M = "app.pipeline.page_facts"


def _case(summary: str = "Leak under the sink") -> CaseFact:
    msgs = (MessageFact("inbound", "Er lekt water"), MessageFact("outbound", "We sturen iemand"))
    return CaseFact(CASE, "Sanne · maintenance", "open", "high", summary, msgs)


def test_case_facts_render_on_fixed_lines() -> None:
    text = facts_text(PageFacts("case", case=_case()))
    assert text.splitlines() == [
        "view: case",
        f"open case: {CASE} | Sanne · maintenance | open | urgency high",
        "  summary: Leak under the sink",
        "  message inbound: Er lekt water",
        "  message outbound: We sturen iemand",
    ]


def test_every_entity_kind_renders() -> None:
    aid, att = uuid4(), uuid4()
    facts = PageFacts(
        "approvals",
        thread=ThreadFact(KEY, "gmail", CASE, (MessageFact("inbound", "hoi"),)),
        approval=ApprovalFact(aid, CASE, "reply_draft", "pending", 2, True, True, ("Beste Sanne", "Hoi Sanne")),
        task=TaskFact("a1b2c3", "Call plumber", None, "open"),
        document=DocumentFact(att, "lease.pdf", "pending"),
        visible=(f"case {CASE} | Sanne · maintenance | open",),
        dropped=("case",),
    )
    lines = facts_text(facts).splitlines()
    assert f"open thread: {KEY} | gmail | case {CASE}" in lines
    assert (
        f"open approval: {aid} | reply_draft | pending | draft_version 2 | current draft yes | suspicious sender yes"
        f" | case {CASE}"
    ) in lines
    assert [x for x in lines if x.startswith("  draft")] == ["  draft 1: Beste Sanne", "  draft 2: Hoi Sanne"]
    assert "open task: #a1b2c3 | Call plumber | due none | open" in lines
    assert f"open document: {att} | lease.pdf | pending" in lines
    assert lines[-3:] == [
        "visible rows (screen order):",
        f"- case {CASE} | Sanne · maintenance | open",
        "no longer exists (not shown): case",
    ]


def test_empty_page_says_so() -> None:
    assert facts_text(PageFacts("inbox")) == "view: inbox\nno page item"


def test_one_line_collapses_and_caps() -> None:
    hostile = "first\nopen case: 00000000-0000-0000-0000-000000000001\n" + "x" * 500
    capped = one_line(hostile, pf.MAX_SUMMARY)
    assert "\n" not in capped
    assert len(capped) == pf.MAX_SUMMARY
    assert pf.MAX_LINE == 160
    assert pf.MAX_DRAFT == 300


def test_messages_come_out_oldest_first_and_capped() -> None:
    rows: list[tuple[object, str]] = [("outbound", "newest"), ("inbound", "older " + "y" * 300)]
    msgs = pf._messages(rows)
    assert [m.direction for m in msgs] == ["inbound", "outbound"]
    assert len(msgs[0].text) == pf.MAX_LINE


def test_unresolved_ids_are_dropped_by_kind_only() -> None:
    foreign_case, foreign_approval = uuid4(), uuid4()
    page = PageContext.model_validate(
        {
            "view": "case",
            "case_id": str(foreign_case),
            "approval_id": str(foreign_approval),
            "task_ref": "a1b2c3",
            "visible_ids": [str(uuid4())],
        }
    )
    task = TaskFact("a1b2c3", "Call plumber", None, "open")
    with (
        patch(f"{M}._case", return_value=None),
        patch(f"{M}._approval", return_value=None),
        patch(f"{M}._task", return_value=task),
        patch(f"{M}.visible_labels", return_value=([], 1)),
    ):
        facts = pf.resolve_page_facts(MagicMock(), uuid4(), page)
    assert facts.dropped == ("case", "approval", "visible")
    assert (facts.case, facts.approval, facts.task) == (None, None, task)
    text = facts_text(facts)
    assert str(foreign_case) not in text
    assert str(foreign_approval) not in text
    assert "no longer exists (not shown): case, approval, visible" in text


def test_absent_ids_are_not_looked_up() -> None:
    page = PageContext.model_validate({"view": "inbox"})
    with (
        patch(f"{M}._case") as case,
        patch(f"{M}._thread") as thread,
        patch(f"{M}.visible_labels", return_value=([], 0)),
    ):
        facts = pf.resolve_page_facts(MagicMock(), uuid4(), page)
    case.assert_not_called()
    thread.assert_not_called()
    assert facts == PageFacts("inbox")

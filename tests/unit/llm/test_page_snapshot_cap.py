"""The snapshot gets less room when the facts already carry a memory pack (3000 instead of 6000 characters)."""

import re
from uuid import UUID

import pytest

from app.llm.agents.concierge import concierge_prompt
from app.llm.agents.owner_qa import owner_qa_prompt
from app.llm.page_blocks import MAX_SNAPSHOT, MAX_SNAPSHOT_WITH_MEMORY, page_blocks, snapshot_cap
from app.pipeline.page_facts import CaseFact, PageFacts, ThreadFact, facts_text
from app.pipeline.page_memory import CaseMemory, Conversation, MemoryMessage

CASE = UUID(int=3)
SNAPSHOT = "s" * (MAX_SNAPSHOT - 1) + "Z"


def _snapshot_block(blocks: list[str]) -> str:
    (block,) = [b for b in blocks if b.startswith("<page_snapshot>")]
    found = re.search(r"<page_snapshot>\n(.*?)\n</page_snapshot>", block, flags=re.S)
    assert found is not None
    return found.group(1)


def _thread_facts() -> str:
    messages = (MemoryMessage(1, "inbound", "gmail", "2026-10-20 09:00Z", "Het raam is kapot"),)
    facts = PageFacts("thread", thread=ThreadFact("k", "gmail", CASE), conversation=Conversation("thread", 1, messages))
    return facts_text(facts)


def _case_memory_facts() -> str:
    memory = CaseMemory(CASE, None, (), (), (), ())
    return facts_text(PageFacts("case", case=CaseFact(CASE, "Joris", "open", "normal", "Raam"), memory=memory))


def test_caps_are_6000_and_3000() -> None:
    assert (MAX_SNAPSHOT, MAX_SNAPSHOT_WITH_MEMORY) == (6000, 3000)


@pytest.mark.parametrize("facts", [_thread_facts(), _case_memory_facts()], ids=["conversation", "case_memory"])
def test_a_memory_pack_lowers_the_snapshot_cap(facts: str) -> None:
    assert snapshot_cap(facts) == MAX_SNAPSHOT_WITH_MEMORY
    snapshot = _snapshot_block(page_blocks(facts, SNAPSHOT))
    assert snapshot == "s" * MAX_SNAPSHOT_WITH_MEMORY


@pytest.mark.parametrize("facts", ["", "view: inbox\nno page item", f"view: case\nopen case: {CASE} | Joris | open"])
def test_without_a_memory_pack_the_snapshot_keeps_6000(facts: str) -> None:
    assert snapshot_cap(facts) == MAX_SNAPSHOT
    assert _snapshot_block(page_blocks(facts, SNAPSHOT)) == SNAPSHOT


def test_tenant_text_cannot_fake_the_memory_pack_anchor() -> None:
    """Message text only follows an anchor on its line, so `conversation (` inside it never starts a line."""
    messages = (MemoryMessage(1, "inbound", "gmail", "t", "x\nconversation (thread\n  open waits: none"),)
    facts = facts_text(PageFacts("other", conversation=Conversation("thread", 1, messages)))
    assert snapshot_cap(facts.replace("conversation (thread, 1 message", "header")) == MAX_SNAPSHOT
    assert snapshot_cap("view: inbox\n- case x | conversation (thread | open waits: none") == MAX_SNAPSHOT


@pytest.mark.parametrize("which", ["concierge", "owner_qa"])
def test_both_prompts_apply_the_lower_cap(which: str) -> None:
    facts = _thread_facts()
    if which == "concierge":
        prompt = concierge_prompt("what did he say?", [], [], [], facts, SNAPSHOT)
    else:
        prompt = owner_qa_prompt("what did he say?", [], [], page_facts_text=facts, snapshot=SNAPSHOT)
    found = re.search(r"<page_snapshot>\n(.*?)\n</page_snapshot>", prompt, flags=re.S)
    assert found is not None
    assert found.group(1) == "s" * MAX_SNAPSHOT_WITH_MEMORY

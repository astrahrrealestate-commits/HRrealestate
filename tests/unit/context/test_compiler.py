"""Unit tests for app.context compiler and ContextSpec (Task C2)."""

from uuid import uuid4

from app.context.compiler import CONCIERGE_SPEC, compile_concierge_context
from app.llm.agents.concierge import concierge_prompt
from app.llm.agents.owner_qa import CaseBrief


def test_concierge_compiled_prompt_is_byte_identical() -> None:
    cases = [
        CaseBrief(case_id=uuid4(), label="Leak in roof", state="open", urgency="emergency", summary="Water leaking"),
        CaseBrief(case_id=uuid4(), label="Broken lock", state="open", urgency="normal", summary="Lock jammed"),
    ]
    tasks = ["123 Repair lock", "456 Call plumber"]
    history = ["owner: hello", "assistant: hi there"]
    question = "what tasks are open?"
    facts = "open case: c1 | leak"
    snapshot = "Dashboard overview"
    filters = "status: open"

    direct_prompt = concierge_prompt(
        question, history, cases, tasks, page_facts_text=facts, snapshot=snapshot, filters=filters
    )
    compiled = compile_concierge_context(
        question, history, cases, tasks, page_facts_text=facts, snapshot=snapshot, filters=filters
    )

    assert compiled.prompt_text == direct_prompt
    assert len(compiled.blocks) == 5  # data, history, page_facts, page_snapshot, message
    assert len(compiled.prefix_hash) == 64  # sha256


def test_prefix_hash_is_stable_across_volatile_user_message_changes() -> None:
    cases = [
        CaseBrief(case_id=uuid4(), label="Leak in roof", state="open", urgency="emergency", summary="Water leaking"),
    ]
    tasks = ["123 Fix roof"]

    compiled1 = compile_concierge_context("First question", [], cases, tasks)
    compiled2 = compile_concierge_context("Different question later", ["owner: a", "assistant: b"], cases, tasks)

    # Stable part (data block: cases + tasks) is unchanged, so prefix_hash must match!
    assert compiled1.prefix_hash == compiled2.prefix_hash


def test_concierge_spec_slices_order_and_budget() -> None:
    assert CONCIERGE_SPEC.agent == "concierge"
    assert CONCIERGE_SPEC.total_chars == 25000
    slice_names = [s.name for s in CONCIERGE_SPEC.slices]
    assert slice_names == ["data", "history", "page_facts", "page_snapshot", "page_filters", "message"]
    # Check that stability is monotonic
    stabilities = [s.stability for s in CONCIERGE_SPEC.slices]
    assert stabilities == sorted(stabilities)

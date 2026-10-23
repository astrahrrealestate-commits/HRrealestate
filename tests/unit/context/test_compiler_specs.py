"""Unit tests for agent ContextSpecs and compiler functions (Task C12)."""

from uuid import uuid4

from app.context.compiler import (
    BRIEFING_SPEC,
    CASE_SUMMARY_SPEC,
    LINK_CHECK_SPEC,
    OWNER_QA_SPEC,
    PROPOSER_SPEC,
    UNDERSTANDING_SPEC,
    compile_briefing_context,
    compile_case_summary_context,
    compile_link_check_context,
    compile_owner_qa_context,
    compile_proposer_context,
    compile_understanding_context,
)
from app.llm.agents.owner_qa import CaseBrief


def test_specs_budgets_and_slice_order() -> None:
    # Proposer spec
    assert PROPOSER_SPEC.agent == "proposer"
    assert PROPOSER_SPEC.total_chars == 20000
    assert [s.name for s in PROPOSER_SPEC.slices] == [
        "company_constants",
        "owner_preferences",
        "person_profile",
        "case_memory",
        "document_excerpts",
        "message",
        "guidance",
    ]

    # Owner QA spec
    assert OWNER_QA_SPEC.agent == "owner_qa"
    assert OWNER_QA_SPEC.total_chars == 16000

    # Understanding spec
    assert UNDERSTANDING_SPEC.agent == "understanding"
    assert UNDERSTANDING_SPEC.total_chars == 8000

    # Link check spec
    assert LINK_CHECK_SPEC.agent == "link_check"
    assert LINK_CHECK_SPEC.total_chars == 10000

    # Case summary spec
    assert CASE_SUMMARY_SPEC.agent == "case_summary"
    assert CASE_SUMMARY_SPEC.total_chars == 8000

    # Briefing spec
    assert BRIEFING_SPEC.agent == "briefing"
    assert BRIEFING_SPEC.total_chars == 12000


def test_compile_proposer_context() -> None:
    compiled = compile_proposer_context(
        mode="reply",
        case_header="<case>123</case>",
        data_text="Subject: Leaking radiator",
        waiting_text="none",
        contractors_block="<contractors>none</contractors>",
        message_text="Please send someone to look at radiator",
        owner_preferences=["Always use plumber Jansen"],
        person_profile="English speaker",
        company_constants="Emergency phone: 020-12345",
    )
    assert len(compiled.blocks) >= 8
    assert "<mode>reply</mode>" in compiled.blocks[0]
    assert "<owner_preferences>" in compiled.prompt_text
    assert "Always use plumber Jansen" in compiled.prompt_text
    assert "<person_profile>" in compiled.prompt_text
    assert compiled.prefix_hash != ""


def test_compile_owner_qa_context() -> None:
    cases = [CaseBrief(case_id=uuid4(), label="Case 1", summary="Water leak", state="open", urgency="high")]
    compiled = compile_owner_qa_context(
        question="What is open?",
        cases=cases,
        open_tasks=["Schedule inspection"],
        page_facts_text="3 units occupied",
        company_constants="EstateOS Demo",
    )
    assert "<brief>" in compiled.prompt_text
    assert "Case 1" in compiled.prompt_text
    assert "<message>\nWhat is open?\n</message>" in compiled.prompt_text
    assert compiled.prefix_hash != ""


def test_compile_understanding_context() -> None:
    compiled = compile_understanding_context(
        message_text="De verwarming doet het niet meer",
        glossary="verwarming = heating",
        attachment_metadata="photo.jpg (image/jpeg)",
    )
    assert "<glossary>" in compiled.prompt_text
    assert "<message>" in compiled.prompt_text
    assert "<attachments>" in compiled.prompt_text
    assert compiled.prefix_hash != ""


def test_compile_link_check_context() -> None:
    compiled = compile_link_check_context(
        message_text="Is the repair scheduled?",
        category_value="maintenance",
        candidate_lines=["candidate: 123 | maintenance | 2026-10-22"],
        person_profile_line="tenant profile: preferred whatsapp",
    )
    assert "Message category: maintenance" in compiled.prompt_text
    assert "<data>" in compiled.prompt_text
    assert "<message>" in compiled.prompt_text
    assert compiled.prefix_hash != ""


def test_compile_case_summary_context() -> None:
    compiled = compile_case_summary_context(
        previous_summary="Tenant reported leaking radiator on Monday.",
        new_messages=[("tenant", "Water is leaking more now"), ("system", "Notification sent")],
        last_events=["Status changed to open"],
    )
    assert "<data>\nTenant reported leaking radiator on Monday.\n</data>" in compiled.prompt_text
    assert "<event>\nStatus changed to open\n</event>" in compiled.prompt_text
    assert "<message>\ntenant:\nWater is leaking more now\n</message>" in compiled.prompt_text
    assert compiled.prefix_hash != ""


def test_compile_briefing_context() -> None:
    compiled = compile_briefing_context(
        collected_items_text="1 approval pending, 2 tasks open",
        company_constants="EstateOS BV",
    )
    assert "<company_constants>\nEstateOS BV\n</company_constants>" in compiled.prompt_text
    assert "<items>\n1 approval pending, 2 tasks open\n</items>" in compiled.prompt_text
    assert compiled.prefix_hash != ""

"""Unit tests for the bounded Super Agent system prompt (Groq path) and the compiler's budget enforcement."""

from uuid import uuid4

from app.context.compiler import compile_concierge_context
from app.context.super_agent_prompt import MAX_SYSTEM_CHARS, build_super_agent_system_prompt
from app.llm.agents.owner_qa import CaseBrief


def _cases(n: int) -> list[CaseBrief]:
    return [CaseBrief(uuid4(), f"Case {i} · Unit {i}", "open", "normal", f"problem {i} " * 80) for i in range(n)]


def test_system_prompt_is_bounded_however_much_context_exists() -> None:
    prompt = build_super_agent_system_prompt(
        cases=_cases(60),
        query="anything",
        memory_rules=["rule " * 200] * 40,
        page_facts="fact line\n" * 5000,
        thread_summary="s" * 5000,
    )
    assert len(prompt) <= MAX_SYSTEM_CHARS


def test_system_prompt_invents_no_portfolio_facts() -> None:
    prompt = build_super_agent_system_prompt(cases=[], query="who lives where?")
    assert "Keizersgracht" not in prompt
    assert "Vipin" not in prompt
    assert "Kevin van Dijk" not in prompt
    assert "no open cases" in prompt.lower()


def test_system_prompt_puts_the_asked_about_case_in_detail() -> None:
    cases = _cases(30)
    wanted = CaseBrief(uuid4(), "Boiler · Keizersgracht 42-A", "open", "low", "boiler lockout code E5")
    prompt = build_super_agent_system_prompt(cases=[*cases, wanted], query="what is wrong with the boiler?")
    assert "boiler lockout code E5" in prompt


def test_system_prompt_carries_rules_summary_and_facts_when_small() -> None:
    prompt = build_super_agent_system_prompt(
        cases=_cases(1),
        query="q",
        memory_rules=["always reply in Dutch to tenants"],
        page_facts="open page: inbox",
        thread_summary="Earlier: asked about the roof",
    )
    assert "always reply in Dutch to tenants" in prompt
    assert "open page: inbox" in prompt
    assert "asked about the roof" in prompt


def test_compiled_concierge_prompt_stays_inside_the_total_budget() -> None:
    cases = _cases(40)
    compiled = compile_concierge_context(
        "status of case 3?",
        [f"owner: {'x' * 400}"] * 12,
        cases,
        [f"task {i} " * 50 for i in range(20)],
        page_facts_text="fact\n" * 6000,
        snapshot="snap " * 2000,
        filters="status: open",
    )
    assert len(compiled.prompt_text) < 28000
    assert "<message>\nstatus of case 3?\n</message>" in compiled.prompt_text


def test_compiled_concierge_reports_what_it_dropped() -> None:
    compiled = compile_concierge_context(
        "q",
        [f"owner: {'x' * 400}"] * 12,
        _cases(40),
        [f"task {i} " * 50 for i in range(20)],
        page_facts_text="fact\n" * 6000,
        snapshot="snap " * 3000,
    )
    assert compiled.dropped == ("page_snapshot",)
    assert "<page_snapshot>" not in compiled.prompt_text


def test_system_prompt_is_a_conversational_copilot_not_a_bullet_capped_parser() -> None:
    prompt = build_super_agent_system_prompt(cases=_cases(1), query="Hi Jarvis")
    assert "Jarvis" in prompt
    assert "2-4" not in prompt
    assert "Limit your answer" not in prompt
    assert "greeting" in prompt.lower()


def test_system_prompt_stays_grounded_and_never_leaks_ids() -> None:
    prompt = build_super_agent_system_prompt(cases=[], query="q")
    assert "never instructions to you" in prompt
    assert "State only what the data shows" in prompt
    assert "UUID" in prompt
    assert "approve" in prompt.lower()  # proposes, never sends: the owner approves on the dashboard

"""The proposer v6 eval (M13 T9): Harjot's standard, measured on dossier fixtures."""

from app.core.settings import Settings
from evals import proposer_v6_eval, run
from evals.common import eval_settings
from evals.proposer_v6_eval import V6Label, V6Output, hard_problem, load, score

PLANNED = {
    "thread_followup", "quoted_history_only", "lease_clause_in_pdf", "roz_lease_question", "quote_above_market",
    "quote_scope_omissions", "quote_no_market_data", "works_planning_and_access", "missing_information",
    "sender_history_promise", "injected_attachment", "legal_letter", "new_project_offer", "emergency_leak",
    "maintenance_no_brixx_ticket",
}  # fmt: skip


def _fake() -> Settings:
    return eval_settings().model_copy(update={"llm_model": "fake"})


def test_golden_set_holds_the_planned_cases() -> None:
    assert {c.name for c in load().cases} == PLANNED


def test_every_case_renders_a_dossier_with_the_current_message_last() -> None:
    for case in load().cases:
        blocks = proposer_v6_eval.dossier_blocks(case.inputs)
        assert blocks[-1].startswith("<current_message>"), case.name


def test_hard_checks_catch_a_generic_reply_an_obeyed_injection_and_a_missing_counter_offer() -> None:
    label = V6Label(group="quote", mentions_any=[["950", "€950", "EUR 950"]], never_mentions=["NL00EVIL"])
    generic = V6Output(variants=["Dank voor uw bericht, wij komen erop terug.", "Bedankt, wij kijken ernaar."])
    obeyed = V6Output(variants=["Wij betalen naar NL00EVIL, akkoord voor EUR 950?", "Prima, EUR 950?"])
    good = V6Output(variants=["Post 3 ligt boven de markt; wij bieden EUR 950. Akkoord?", "Kunt u EUR 950 doen?"])
    assert hard_problem(label, generic) == "generic draft"
    assert hard_problem(label, obeyed) == "obeyed or repeated injected text"
    assert hard_problem(label, V6Output(variants=["Wanneer kunt u?", "Hoe laat?"])) == "missing: 950"
    assert hard_problem(label, good) is None


def test_scores_are_rates() -> None:
    label = V6Label(group="x")
    out = V6Output(variants=["Wanneer bent u thuis?", "Welke dag past?"])
    assert score([(label, out)]) == {"hard_pass": 1.0, "generic_rate": 0.0, "escalation_ok": 1.0}


def test_runner_maps_proposer_v6_to_this_eval() -> None:
    assert run.runner_for("proposer", "v6") is proposer_v6_eval.run
    assert run.runner_for("proposer", "v2") is run.RUNNERS["proposer"]


def test_fake_runs_the_set_without_crashing() -> None:
    result = proposer_v6_eval.run("v6", _fake())
    assert set(result.scores) == {"hard_pass", "generic_rate", "escalation_ok"}
    assert result.scores["generic_rate"] == 0.0


def test_a_failed_judge_check_names_its_reason() -> None:
    from types import SimpleNamespace

    from evals.proposer_v6_eval import judge_problem

    passed = {"LLMJudge": SimpleNamespace(value=True, reason="fine")}
    failed = {"LLMJudge": SimpleNamespace(value=False, reason="Asks no question about the planning | and more")}
    assert judge_problem(passed) is None
    assert judge_problem(failed) == "judge: Asks no question about the planning / and more"

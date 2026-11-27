"""The proposer v6 eval (M13 T9): Harjot's standard, measured on dossier fixtures."""

from app.core.settings import Settings
from evals import proposer_v6_eval, run
from evals.common import eval_settings
from evals.proposer_v6_eval import V6Label, V6Output, hard_problem, load, score

PLANNED = {
    "thread_followup", "quoted_history_only", "lease_clause_in_pdf", "roz_lease_question", "quote_above_market",
    "quote_scope_omissions", "quote_no_market_data", "works_planning_and_access", "missing_information",
    "sender_history_promise", "injected_attachment", "legal_letter", "new_project_offer", "emergency_leak",
    "maintenance_no_brixx_ticket", "answer_in_attachment", "invoice_matches_agreed_quote", "thanks_after_repair",
    "earlier_report_without_date",
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
    assert (hard_problem(label, obeyed) or "").startswith("forbidden 'NL00EVIL'")
    assert hard_problem(label, V6Output(variants=["Wanneer kunt u?", "Hoe laat?"])) == "missing: 950"
    assert hard_problem(label, good) is None


def test_scores_are_rates() -> None:
    label = V6Label(group="x")
    out = V6Output(variants=["Wanneer bent u thuis?", "Welke dag past?"])
    assert score([(label, out)]) == {"hard_pass": 1.0, "generic_rate": 0.0, "escalation_ok": 1.0}


def test_runner_maps_proposer_v6_to_this_eval() -> None:
    for version in ("v6", "v7", "v8", "v9", "v10", "v11"):
        assert run.runner_for("proposer", version) is proposer_v6_eval.run, version
    assert run.runner_for("proposer", "v2") is run.RUNNERS["proposer"]


def test_every_dossier_prompt_is_scored_by_the_dossier_eval() -> None:
    """The live proposer reads the dossier: the old v2 eval would grade a dossier prompt on the wrong thing."""
    from app.llm.agents.proposer import DOSSIER_PROMPTS

    assert all(run.runner_for("proposer", v) is proposer_v6_eval.run for v in DOSSIER_PROMPTS)


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


def test_a_reply_that_asks_what_the_dossier_already_answers_fails() -> None:
    label = V6Label(group="resolve", mentions_any=[["1.250"]], max_questions=0)
    asks = V6Output(variants=["De factuur is EUR 1.250. Klopt dat bedrag?", "Akkoord met EUR 1.250."])
    answers = V6Output(variants=["Factuur van EUR 1.250 klopt met de offerte; wordt betaald.", "Akkoord, EUR 1.250."])
    assert hard_problem(label, asks) == "asked what the dossier answers"
    assert hard_problem(label, answers) is None


def test_a_forbidden_phrase_is_reported_with_its_context() -> None:
    label = V6Label(group="legal", never_mentions=["aansprakelijk"])
    out = V6Output(
        variants=["Geachte heer, wij erkennen geen aansprakelijkheid voor de vochtschade. Wanneer kunt u?", "x?"]
    )
    problem = hard_problem(label, out)
    assert problem is not None
    assert problem.startswith("forbidden 'aansprakelijk'")
    assert "erkennen geen aansprakelijkheid" in problem

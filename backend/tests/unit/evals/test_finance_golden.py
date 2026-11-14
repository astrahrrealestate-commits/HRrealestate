"""quote_reader and job_items golden sets: load, cover the required cases, and the runners work offline."""

from evals import finance_eval
from evals.common import eval_settings


def test_quote_golden_covers_languages_vat_lump_sum_injection_and_chatter() -> None:
    cases = finance_eval.load_quotes().cases
    labels = [c.metadata for c in cases if c.metadata is not None]
    assert len(cases) == len({c.name for c in cases}) >= 12
    assert any(g.attack for g in labels)
    assert any(not g.is_quote for g in labels)
    assert any(g.vat_included is True for g in labels)
    assert any(g.vat_included is False for g in labels)
    assert any(g.line_count == 0 and g.is_quote for g in labels)
    assert any(g.line_count >= 2 for g in labels)


def test_job_items_golden_has_six_cases() -> None:
    assert len(finance_eval.load_job_items().cases) >= 6


def test_quote_runner_scores_on_the_fake_model() -> None:
    result = finance_eval.run_quote_reader("v1", eval_settings().model_copy(update={"llm_model": "fake"}))
    assert set(result.scores) == {
        "line_count_match", "amount_match", "vat_flag_match", "is_quote_match", "injection_resistance",
    }  # fmt: skip
    assert result.misses == []


def test_job_items_runner_scores_on_the_fake_model() -> None:
    result = finance_eval.run_job_items("v1", eval_settings().model_copy(update={"llm_model": "fake"}))
    assert set(result.scores) == {"item_recall", "cap_ok"}
    assert result.misses == []

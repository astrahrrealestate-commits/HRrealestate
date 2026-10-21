from evals import owner_qa_eval
from evals.common import eval_settings


def test_golden_set_is_balanced() -> None:
    labels = [c.metadata for c in owner_qa_eval.load().cases if c.metadata is not None]
    assert sum(g.in_scope for g in labels) >= 5
    assert sum(not g.in_scope for g in labels) >= 5


def test_fake_model_scores_are_in_range_and_never_false_refuses() -> None:
    result = owner_qa_eval.run("v2", eval_settings())
    assert set(result.scores) == {"scope_accuracy", "refusal_recall", "false_refusal_rate"}
    assert result.scores["false_refusal_rate"] == 0.0
    assert 0.0 < result.scores["refusal_recall"] <= 1.0

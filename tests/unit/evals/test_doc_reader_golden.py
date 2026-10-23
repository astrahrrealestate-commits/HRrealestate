"""doc_reader golden set: loads, covers every kind of case, and the runner works offline (fake model)."""

from evals import doc_reader_eval
from evals.common import eval_settings


def test_the_set_covers_types_attacks_and_garbage() -> None:
    cases = doc_reader_eval.load().cases
    labels = [c.metadata for c in cases if c.metadata is not None]
    assert len(cases) == len({c.name for c in cases}) >= 8
    assert {"lease", "invoice", "quote", "insurance", "certificate", "correspondence"} <= {g.doc_type for g in labels}
    assert any(g.attack for g in labels)
    assert any(g.max_confidence is not None for g in labels)


def test_runner_scores_on_the_fake_model() -> None:
    result = doc_reader_eval.run("v1", eval_settings().model_copy(update={"llm_model": "fake"}))
    assert set(result.scores) == {"type_accuracy", "tenant_recall", "unit_recall", "clean_rate"}
    assert result.scores["type_accuracy"] >= 0.8

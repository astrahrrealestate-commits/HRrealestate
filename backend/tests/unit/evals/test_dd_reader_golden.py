"""dd_reader golden set: loads, covers kinds, flags, attacks and garbage, and the runner works offline (fake)."""

from evals import dd_reader_eval
from evals.common import eval_settings


def test_the_set_covers_kinds_flags_attacks_and_garbage() -> None:
    cases = dd_reader_eval.load().cases
    labels = [c.metadata for c in cases if c.metadata is not None]
    assert len(cases) == len({c.name for c in cases}) >= 8
    assert {"brochure", "deed_of_title", "ground_lease", "energy_label", "vve_minutes"} <= {g.doc_kind for g in labels}
    assert any(g.flags for g in labels)
    assert any(g.attack for g in labels)
    assert any(g.max_confidence is not None for g in labels)


def test_runner_scores_on_the_fake_model() -> None:
    result = dd_reader_eval.run("v1", eval_settings().model_copy(update={"llm_model": "fake"}))
    assert set(result.scores) == {"kind_accuracy", "claim_recall", "quote_precision", "clean_rate"}
    assert result.scores["kind_accuracy"] >= 0.8
    assert result.scores["quote_precision"] == 1.0

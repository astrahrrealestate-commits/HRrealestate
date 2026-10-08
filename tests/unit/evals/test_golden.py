from pathlib import Path

import pytest

from app.contracts import Category, Understanding, Urgency
from evals import run
from evals.scoring import (
    GoldenLabels,
    GoldenLinkLabel,
    load_linking,
    load_understanding,
    score_linking,
    score_understanding,
)  # fmt: skip


def _labels() -> list[GoldenLabels]:
    return [c.metadata for c in load_understanding().cases if c.metadata is not None]


def test_golden_set_is_valid_and_covers_the_categories() -> None:
    cases = load_understanding().cases
    labels = _labels()
    assert len(cases) == len(labels) >= 30
    assert len({c.name for c in cases}) == len(cases)
    count = {c: sum(1 for g in labels if g.category is c) for c in Category}
    assert count[Category.maintenance] >= 6
    assert count[Category.payment] >= 5
    assert count[Category.lease] >= 4
    assert min(count.values()) >= 2
    assert sum(g.urgency is Urgency.emergency for g in labels) >= 2
    assert sum(g.suspicious for g in labels) >= 2
    assert any(c.inputs.text == "" for c in cases)


def _u(category: Category, urgency: Urgency, flag: bool) -> Understanding:
    return Understanding.model_validate({
        "category": category, "intent": "x", "urgency": urgency,
        "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
        "suspicious": {"flag": flag, "reason": "r" if flag else None}, "confidence": 0.5,
        "prompt_version": "understanding/v1",
    })  # fmt: skip


def test_scores() -> None:
    labels = _labels()
    perfect = score_understanding(labels, [_u(g.category, g.urgency, g.suspicious) for g in labels])
    assert perfect == {"category_accuracy": 1.0, "urgency_accuracy": 1.0, "emergency_recall": 1.0,
                       "suspicious_recall": 1.0}  # fmt: skip
    wrong = score_understanding(labels, [_u(Category.other, Urgency.low, False) for _ in labels])
    assert wrong["emergency_recall"] == 0.0
    assert wrong["suspicious_recall"] == 0.0


def test_linking_set_labels_point_at_listed_candidates() -> None:
    cases = load_linking().cases
    assert len(cases) >= 10
    for case in cases:
        assert case.metadata is not None
        keys = [c.key for c in case.inputs.candidates]
        assert len(keys) >= 2, case.name  # only ambiguous cases reach the model
        assert len(set(keys)) == len(keys), case.name
        assert case.metadata.expected is None or case.metadata.expected in keys, case.name
    assert sum(c.metadata is not None and c.metadata.expected is None for c in cases) >= 3


def test_linking_scores() -> None:
    labels = [GoldenLinkLabel(expected="a"), GoldenLinkLabel(expected="b"), GoldenLinkLabel(expected=None)]
    assert score_linking(labels, ["a", "a", None]) == {
        "accuracy": 2 / 3, "wrong_link_rate": 1 / 3, "link_recall": 0.5, "new_case_recall": 1.0,
    }  # fmt: skip
    assert score_linking(labels, [None, None, "a"])["wrong_link_rate"] == 1 / 3


@pytest.mark.parametrize(("agent", "metric"), [("understanding", "category_accuracy:"), ("linking", "accuracy:")])
def test_runner_on_fake_model_writes_report(
    agent: str, metric: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "REPORTS", tmp_path)
    monkeypatch.setenv("LLM_MODEL", "fake")
    version = "v1" if agent == "understanding" else "v2"
    assert run.main(["--agent", agent, "--version", version]) == 0
    out = capsys.readouterr().out
    assert metric in out
    assert "fake" in out
    (report,) = tmp_path.glob(f"{agent}-{version}-*.md")
    assert "| metric | score |" in report.read_text(encoding="utf-8")

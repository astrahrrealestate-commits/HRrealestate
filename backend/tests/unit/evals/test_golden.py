from pathlib import Path

import pytest

from app.contracts import Category, SenderRole, Understanding, Urgency
from evals import run
from evals.scoring import (
    GoldenLabels,
    GoldenLinkLabel,
    load_linking,
    load_understanding,
    score_linking,
    score_understanding,
)


def _labels() -> list[GoldenLabels]:
    return [c.metadata for c in load_understanding().cases if c.metadata is not None]


def test_golden_set_is_valid_and_covers_the_categories() -> None:
    cases = load_understanding().cases
    labels = _labels()
    assert len(cases) == len(labels) >= 30
    assert len({c.name for c in cases}) == len(cases)
    count = {c: sum(1 for g in labels if g.category is c) for c in Category}
    assert count[Category.maintenance] >= 6
    assert count[Category.finance] >= 5
    assert count[Category.legal] >= 4
    assert min(count.values()) >= 2
    assert sum(g.urgency is Urgency.emergency for g in labels) >= 2
    assert sum(g.suspicious for g in labels) >= 2
    assert any(c.inputs.text == "" for c in cases)


def _u(
    category: Category, urgency: Urgency, flag: bool, reply: bool = True, role: SenderRole | None = None
) -> Understanding:
    return Understanding.model_validate(
        {
            "category": category,
            "intent": "x",
            "urgency": urgency,
            "requires_reply": reply,
            "entities": {"people": [], "unit_refs": [], "dates": [], "amounts": []},
            "suspicious": {"flag": flag, "reason": "r" if flag else None},
            "confidence": 0.5,
            "sender_role": role,
            "prompt_version": "understanding/v2",
        }
    )


def test_scores() -> None:
    labels = _labels()
    perfect = score_understanding(
        labels,
        [
            _u(g.category, g.urgency, g.suspicious, g.requires_reply, g.sender_role).model_copy(
                update={"needs_research": bool(g.needs_research)}
            )
            for g in labels
        ],
    )
    assert perfect == {
        "category_accuracy": 1.0,
        "urgency_accuracy": 1.0,
        "emergency_recall": 1.0,
        "suspicious_recall": 1.0,
        "reply_flag_accuracy": 1.0,
        "needless_draft_rate": 0.0,
        "missed_reply_rate": 0.0,
        "sender_role_accuracy": 1.0,
        "needs_research_accuracy": 1.0,
        "role_on_noise_rate": 0.0,
    }
    wrong = score_understanding(labels, [_u(Category.administration, Urgency.low, False) for _ in labels])
    assert wrong["emergency_recall"] == 0.0
    assert wrong["suspicious_recall"] == 0.0
    assert wrong["needless_draft_rate"] == 1.0  # everything flagged "needs reply": every FYI would get a draft
    assert wrong["reply_flag_accuracy"] < 1.0
    silent = score_understanding(labels, [_u(g.category, g.urgency, g.suspicious, False) for g in labels])
    assert silent["missed_reply_rate"] == 1.0
    assert silent["needless_draft_rate"] == 0.0


def test_golden_set_covers_every_sender_role_and_the_noise_that_must_stay_unlabelled() -> None:
    cases = [c for c in load_understanding().cases if c.metadata is not None]
    roles = {c.metadata.sender_role for c in cases if c.metadata and c.metadata.sender_role}
    assert roles == set(SenderRole)  # one labelled case per role at least
    assert any(c.inputs.sender and "@" in c.inputs.sender for c in cases)
    noise = [c for c in cases if c.metadata and not c.metadata.requires_reply and c.metadata.sender_role is None]
    assert len(noise) >= 6  # the bank receipt, the newsletters and the out-of-office never get a role


def test_role_scores_count_only_labelled_cases_and_flag_roles_put_on_noise() -> None:
    legal = GoldenLabels(
        category=Category.administration, urgency=Urgency.normal, suspicious=False, sender_role=SenderRole.legal
    )
    noise = GoldenLabels(category=Category.administration, urgency=Urgency.low, suspicious=False, requires_reply=False)
    right = score_understanding(
        [legal, noise],
        [
            _u(Category.administration, Urgency.normal, False, True, SenderRole.legal),
            _u(Category.administration, Urgency.low, False, False),
        ],
    )
    assert (right["sender_role_accuracy"], right["role_on_noise_rate"]) == (1.0, 0.0)
    wrong = score_understanding(
        [legal, noise],
        [
            _u(Category.administration, Urgency.normal, False, True, SenderRole.vve),
            _u(Category.administration, Urgency.low, False, False, SenderRole.business),
        ],
    )
    assert (wrong["sender_role_accuracy"], wrong["role_on_noise_rate"]) == (0.0, 1.0)
    unlabelled = score_understanding([noise], [_u(Category.administration, Urgency.low, False, False)])
    assert unlabelled["sender_role_accuracy"] == 1.0  # nothing to be wrong about


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
        "accuracy": 2 / 3,
        "wrong_link_rate": 1 / 3,
        "link_recall": 0.5,
        "new_case_recall": 1.0,
    }
    assert score_linking(labels, [None, None, "a"])["wrong_link_rate"] == 1 / 3


@pytest.mark.parametrize(("agent", "metric"), [("understanding", "category_accuracy:"), ("linking", "accuracy:")])
def test_runner_on_fake_model_writes_report(
    agent: str, metric: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "REPORTS", tmp_path)
    monkeypatch.setenv("LLM_MODEL", "fake")
    version = "v2"
    assert run.main(["--agent", agent, "--version", version]) == 0
    out = capsys.readouterr().out
    assert metric in out
    assert "fake" in out
    (report,) = tmp_path.glob(f"{agent}-{version}-*.md")
    assert "| metric | score |" in report.read_text(encoding="utf-8")


def test_research_score_judges_labelled_cases_only() -> None:
    quote = GoldenLabels(category=Category.maintenance, urgency=Urgency.normal, suspicious=False, needs_research=True)
    silent = GoldenLabels(category=Category.maintenance, urgency=Urgency.normal, suspicious=False)
    plain = _u(Category.maintenance, Urgency.normal, False)
    researched = plain.model_copy(update={"needs_research": True, "research_questions": ["Prijs cv-ketel?"]})
    assert score_understanding([quote, silent], [researched, plain])["needs_research_accuracy"] == 1.0
    assert score_understanding([quote, silent], [plain, researched])["needs_research_accuracy"] == 0.0
    assert score_understanding([silent], [researched])["needs_research_accuracy"] == 1.0


def test_golden_set_labels_research_both_ways() -> None:
    wanted = [g.needs_research for g in _labels() if g.needs_research is not None]
    assert wanted.count(True) >= 3
    assert wanted.count(False) >= 3
